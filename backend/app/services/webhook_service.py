"""
Webhook management + delivery (Part 10, spec §55). Secrets are backend-only:
the signing secret is generated server-side, shown once at creation, and every
delivery carries an HMAC-SHA256 signature (X-DigiSNR-Signature) the receiver
can verify. Delivery: 4 attempts (1 + 3 retries), full delivery log, manual
replay is audited.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import string
from datetime import datetime, timezone

from pymongo.errors import PyMongoError

from app.core import audit_actions
from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.db.audit_repository import record as audit_record
from app.db.mongodb import get_database
from app.services.postback_service import validate_outbound_url

logger = logging.getLogger(__name__)

WEBHOOKS = "webhooks"
DELIVERIES = "webhook_deliveries"

SUPPORTED_EVENTS = ["conversion.created", "conversion.status_updated", "campaign.paused", "campaign.ended"]
_RETRY_BACKOFF = [0, 0.5, 1.0, 2.0]
_ALPHABET = string.ascii_uppercase + string.digits


def _new_webhook_id() -> str:
    return "WHK" + "".join(secrets.choice(_ALPHABET) for _ in range(6))


async def create_webhook(name: str, url: str, events: list[str], actor_user_id: str) -> dict:
    validated_url = validate_outbound_url(url)  # SSRF guard shared with postbacks
    unknown = [e for e in events if e not in SUPPORTED_EVENTS]
    if unknown:
        from app.core.exceptions import ValidationAppError

        raise ValidationAppError(f"Unsupported events: {', '.join(unknown)}. Supported: {', '.join(SUPPORTED_EVENTS)}")
    doc = {
        "webhook_id": _new_webhook_id(),
        "name": name,
        "url": validated_url,
        "secret": "whsec_" + secrets.token_urlsafe(24),
        "events": events,
        "enabled": True,
        "created_by": actor_user_id,
        "created_at": datetime.now(timezone.utc),
    }
    db = get_database()
    try:
        await db[WEBHOOKS].insert_one(doc)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Webhook store unavailable") from exc
    await audit_record(
        audit_actions.WEBHOOK_CREATED, actor_user_id=actor_user_id,
        metadata={"webhook_id": doc["webhook_id"], "events": events, "url": validated_url},
    )
    return doc


async def list_webhooks() -> list[dict]:
    db = get_database()
    try:
        docs = await db[WEBHOOKS].find({}).sort("created_at", -1).to_list(length=200)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Webhook store unavailable") from exc
    return [
        {
            "webhook_id": w["webhook_id"], "name": w["name"], "url": w["url"], "events": w["events"],
            "enabled": w["enabled"], "created_at": w["created_at"],
        }
        for w in docs
    ]


async def get_webhook(webhook_id: str) -> dict | None:
    db = get_database()
    try:
        return await db[WEBHOOKS].find_one({"webhook_id": webhook_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Webhook store unavailable") from exc


async def set_webhook_enabled(webhook_id: str, enabled: bool, actor_user_id: str) -> dict:
    db = get_database()
    try:
        await db[WEBHOOKS].update_one({"webhook_id": webhook_id}, {"$set": {"enabled": enabled}})
        doc = await db[WEBHOOKS].find_one({"webhook_id": webhook_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Webhook store unavailable") from exc
    if doc is None:
        raise NotFoundError("Webhook not found")
    await audit_record(
        audit_actions.WEBHOOK_TOGGLED, actor_user_id=actor_user_id,
        metadata={"webhook_id": webhook_id, "enabled": enabled},
    )
    return doc


def sign_payload(secret: str, payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode()
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _http_post(url: str, payload: dict, signature: str) -> tuple[int | None, str | None]:
    """Single delivery attempt — isolated so tests can substitute it."""
    import httpx

    from app.core.net_safety import UnsafeDestination, assert_public_destination

    try:
        await assert_public_destination(url)
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            resp = await client.post(
                url,
                content=json.dumps(payload, default=str),
                headers={"Content-Type": "application/json", "X-DigiSNR-Signature": signature},
            )
            return resp.status_code, resp.text[:200]
    except UnsafeDestination:
        return None, "destination not allowed"
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)[:200]


async def dispatch_event(event: str, payload: dict) -> None:
    """Fire webhooks subscribed to `event`. Never raises — delivery failures
    are recorded, never fatal to the business operation that triggered them."""
    db = get_database()
    try:
        hooks = await db[WEBHOOKS].find({"enabled": True, "events": event}).to_list(length=100)
    except PyMongoError as exc:
        logger.error("webhook lookup failed: %s", exc)
        return

    for hook in hooks:
        signature = sign_payload(hook["secret"], payload)
        attempts = []
        final_status = "failed"
        for index, backoff in enumerate(_RETRY_BACKOFF):
            if backoff:
                await asyncio.sleep(backoff)
            http_status, error = await _http_post(hook["url"], payload, signature)
            attempts.append({
                "attempt": index + 1, "sent_at": datetime.now(timezone.utc),
                "http_status": http_status, "error": error,
            })
            if http_status is not None and 200 <= http_status < 300:
                final_status = "delivered"
                break
        try:
            await db[DELIVERIES].insert_one({
                "delivery_id": "WHD" + "".join(secrets.choice(_ALPHABET) for _ in range(6)),
                "webhook_id": hook["webhook_id"], "event": event,
                "payload": payload,
                "payload_preview": json.dumps(payload, default=str)[:300],
                "attempts": attempts, "attempt_count": len(attempts),
                "final_status": final_status, "created_at": datetime.now(timezone.utc),
            })
        except PyMongoError as exc:
            logger.error("webhook delivery log failed: %s", exc)


async def list_deliveries(webhook_id: str | None = None, limit: int = 50) -> list[dict]:
    db = get_database()
    query = {"webhook_id": webhook_id} if webhook_id else {}
    try:
        docs = await db[DELIVERIES].find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Webhook store unavailable") from exc
    return [
        {
            "delivery_id": d["delivery_id"], "webhook_id": d["webhook_id"], "event": d["event"],
            "attempt_count": d["attempt_count"], "final_status": d["final_status"], "created_at": d["created_at"],
        }
        for d in docs
    ]


async def replay_delivery(delivery_id: str, actor_user_id: str) -> dict:
    db = get_database()
    try:
        delivery = await db[DELIVERIES].find_one({"delivery_id": delivery_id})
        hook = await db[WEBHOOKS].find_one({"webhook_id": delivery["webhook_id"]}) if delivery else None
    except PyMongoError as exc:
        raise ServiceUnavailableError("Webhook store unavailable") from exc
    if delivery is None or hook is None:
        raise NotFoundError("Delivery not found")

    payload = delivery.get("payload") or {}
    http_status, error = await _http_post(hook["url"], payload, sign_payload(hook["secret"], payload))
    attempts = list(delivery["attempts"])
    attempts.append({
        "attempt": len(attempts) + 1, "sent_at": datetime.now(timezone.utc),
        "http_status": http_status, "error": error, "manual": True,
    })
    delivered = http_status is not None and 200 <= http_status < 300
    try:
        await db[DELIVERIES].update_one(
            {"delivery_id": delivery_id},
            {"$set": {"attempts": attempts, "attempt_count": len(attempts),
                      "final_status": "delivered" if delivered else "failed",
                      "replayed_by": actor_user_id, "replayed_at": datetime.now(timezone.utc)}},
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Webhook store unavailable") from exc
    await audit_record(
        audit_actions.WEBHOOK_REPLAYED, actor_user_id=actor_user_id,
        metadata={"delivery_id": delivery_id, "result": "delivered" if delivered else "failed"},
    )
    updated = await db[DELIVERIES].find_one({"delivery_id": delivery_id})
    return {
        "delivery_id": updated["delivery_id"], "webhook_id": updated["webhook_id"], "event": updated["event"],
        "attempt_count": updated["attempt_count"], "final_status": updated["final_status"],
        "created_at": updated["created_at"],
    }
