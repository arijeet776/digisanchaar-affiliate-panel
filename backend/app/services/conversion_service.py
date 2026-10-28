"""Conversion engine (Part 6) — platform-agnostic. Adapters normalize;
this engine resolves identity, enforces idempotency, and records conversions.
Server-authoritative: campaign/publisher/manager/payout come from stored
records (click + campaign config), NEVER from postback parameters (spec §22).
"""
import logging
from datetime import datetime, timezone

from app.core import audit_actions
from app.core.enums import CampaignStatus
from app.core.exceptions import ValidationAppError
from app.db import campaign_repository, conversion_repository
from app.db.audit_repository import record as audit_record
from app.db.mongodb import get_database
from app.services import postback_adapters, postback_service

logger = logging.getLogger(__name__)

# Campaigns in these states accept conversions for EXISTING clicks —
# including legitimate late postbacks after a campaign ends (spec §13).
_CONVERSION_ACCEPTING = {CampaignStatus.ACTIVE.value, CampaignStatus.PAUSED.value, CampaignStatus.ENDED.value}

_VELOCITY_FLAG_THRESHOLD = 50  # clicks/IP/hour — recorded as a signal only, never auto-fraud (§36)


def _idempotency_key(platform: str, canonical: dict, digisnr_click_id: str) -> str:
    event = canonical.get("event") or canonical.get("goal") or ""
    return f"{platform}|{canonical.get('external_conversion_id') or ''}|{event}|{digisnr_click_id}"


async def _resolve_payout(campaign_id: str, event_name: str | None) -> tuple[float | None, str | None]:
    """Publisher payout comes from the campaign's configured events — the
    client can never forge it (spec §22). Returns (payout, note)."""
    if not event_name:
        return None, "no_event_supplied"
    campaign = await campaign_repository.get_campaign(campaign_id)
    if campaign is None:
        return None, "campaign_missing"
    version = await campaign_repository.get_current_config(campaign)
    if version is None:
        return None, "config_missing"
    for ev in version.get("events", []):
        if ev["event_name"].lower() == event_name.lower():
            return ev["payout"], None
    return None, "no_matching_event"


async def _awaits_company_report(campaign_id: str) -> bool:
    """A campaign with a validation window (tracking_window_hours) is settled
    from the advertiser's own report, not from the postback's claim."""
    campaign = await campaign_repository.get_campaign(campaign_id)
    if campaign is None:
        return False
    version = await campaign_repository.get_current_config(campaign)
    return bool(version and version.get("tracking_window_hours"))


async def _ip_velocity_flag(ip: str | None) -> bool:
    if not ip:
        return False
    db = get_database()
    since = datetime.now(timezone.utc).timestamp() - 3600
    count = await db["clicks"].count_documents(
        {"ip": ip, "click_created_at": {"$gte": datetime.fromtimestamp(since, timezone.utc)}}
    )
    return count > _VELOCITY_FLAG_THRESHOLD


async def process_inbound(platform: str, token: str, params: dict, request_id: str | None) -> dict:
    """Returns {http_status, body}. Unknown/disabled endpoints get a bare 404 —
    no information about platforms or campaigns leaks to anonymous callers."""
    endpoint = await conversion_repository.get_endpoint_by_token(platform, token)
    if endpoint is None or endpoint["status"] != "active":
        return {"http_status": 404, "body": {"status": "error"}}

    async def finalize(status_: str, http: int, conversion_id=None, error=None, canonical=None, click=None):
        await conversion_repository.log_inbound({
            "endpoint_id": endpoint["endpoint_id"],
            "platform": platform,
            "campaign_id": endpoint["campaign_id"],
            "processing_status": status_,
            "conversion_id": conversion_id,
            "error": error,
            "event": (canonical or {}).get("event") or (canonical or {}).get("goal"),
            "status": (canonical or {}).get("status"),
            "digisnr_click_id": (canonical or {}).get("digisnr_click_id"),
            "external_click_id": (canonical or {}).get("external_click_id"),
            "agency_click_id": (canonical or {}).get("agency_click_id"),
            "external_conversion_id": (canonical or {}).get("external_conversion_id"),
            "payout": (canonical or {}).get("upstream_payout"),
            "revenue": (canonical or {}).get("advertiser_revenue"),
            "currency": (canonical or {}).get("currency"),
            "raw_platform_parameters": (canonical or {}).get("raw_platform_parameters"),
            "request_id": request_id,
        })
        await conversion_repository.bump_endpoint_stats(endpoint["endpoint_id"], failed=http >= 400)
        return {"http_status": http, "body": {"status": "ok" if http < 400 else "error"}}

    campaign = await campaign_repository.get_campaign(endpoint["campaign_id"])
    if campaign is None or campaign["status"] not in _CONVERSION_ACCEPTING:
        return await finalize("rejected", 200, error="campaign_not_accepting")

    config = await campaign_repository.get_current_config(campaign) or {}
    mapping = {k: config.get(k) for k in ("click_id_param", "advertiser_click_id_param", "campaign_title_param", "event_param", "extra_click_id_params")}
    try:
        if mapping.get("click_id_param"):
            canonical = postback_adapters.normalize_mapped(platform, params, mapping)
        else:  # campaign created before macro mapping existed — legacy per-platform adapter
            canonical = postback_adapters.normalize(platform, params)
    except ValidationAppError as exc:
        return await finalize("malformed", 400, error=str(exc))

    # Click resolution (spec §16): DigiSNR click id first. The resolved click
    # MUST belong to this endpoint's campaign — a click from another campaign
    # can never convert here (anti-forgery, §22/§34).
    qx_click_id = canonical.get("digisnr_click_id")
    click = await conversion_repository.get_click(qx_click_id) if qx_click_id else None
    if click is None or click["campaign_id"] != endpoint["campaign_id"]:
        return await finalize("unresolved", 200, error="click_not_resolved", canonical=canonical)

    idem_key = _idempotency_key(platform, canonical, qx_click_id)
    now = datetime.now(timezone.utc)

    # Keep the advertiser's own click id next to ours (Super Admin sees both).
    if canonical.get("external_click_id") and not click.get("external_click_id"):
        try:
            await get_database()["clicks"].update_one(
                {"digisnr_click_id": qx_click_id},
                {"$set": {"external_click_id": canonical["external_click_id"]}},
            )
        except Exception as exc:  # noqa: BLE001 — bookkeeping only, never blocks the conversion
            logger.warning("could not store advertiser click id for %s: %s", qx_click_id, exc)

    # Idempotency (spec §23): duplicate postback → existing conversion; a
    # changed status is a legitimate update to the SAME conversion (§20).
    existing = await get_database()["conversions"].find_one({"idempotency_key": idem_key})
    if existing is not None:
        new_status = canonical.get("status")
        if new_status and new_status != existing.get("status"):
            await conversion_repository.update_conversion_status(
                existing["conversion_id"], new_status, canonical.get("raw_status")
            )
            await audit_record(
                audit_actions.CONVERSION_STATUS_UPDATED, actor_user_id="system",
                metadata={"conversion_id": existing["conversion_id"], "old": existing.get("status"), "new": new_status},
            )
        return await finalize("duplicate", 200, conversion_id=existing["conversion_id"], canonical=canonical, click=click)

    payout, payout_note = await _resolve_payout(endpoint["campaign_id"], canonical.get("event") or canonical.get("goal"))
    suspicious = await _ip_velocity_flag(click.get("ip"))
    awaits_report = await _awaits_company_report(endpoint["campaign_id"])

    conversion_doc = {
        "idempotency_key": idem_key,
        "platform": platform,
        "campaign_id": endpoint["campaign_id"],
        "campaign_code": click.get("campaign_code"),
        "publisher_id": click["publisher_id"],
        "publisher_code": click.get("publisher_code"),
        "manager_id": click["manager_id"],
        "link_id": click["link_id"],
        "digisnr_click_id": qx_click_id,
        "external_click_id": canonical.get("external_click_id"),
        "agency_click_id": canonical.get("agency_click_id"),
        "sub_affiliate_id": canonical.get("sub_affiliate_id"),
        "external_conversion_id": canonical.get("external_conversion_id"),
        "event": canonical.get("event"),
        "goal": canonical.get("goal"),
        "campaign_title": canonical.get("campaign_title"),
        "raw_event_value": canonical.get("raw_event_value"),
        "raw_goal_value": canonical.get("raw_goal_value"),
        "status": canonical.get("status"),
        "raw_status": canonical.get("raw_status"),
        "advertiser_revenue": canonical.get("advertiser_revenue"),
        "upstream_payout": canonical.get("upstream_payout"),
        "sale_amount": canonical.get("sale_amount"),
        "currency": canonical.get("currency"),
        "payout": payout,
        "payout_note": payout_note,
        # pending_report => earning is created only when the company's report
        # is recorded (conversion_review_service). No window => legacy
        # behaviour: earned at postback time.
        "approval_status": "pending_report" if awaits_report else "confirmed",
        "suspicious_velocity": suspicious,
        "sub_ids": canonical.get("sub_ids") or {},
        "utm": canonical.get("utm") or {},
        "click_created_at": click.get("click_created_at"),
        "event_occurred_at": canonical.get("event_occurred_at"),
        "postback_received_at": now,
        "config_version": click.get("config_version"),
        "request_id": request_id,
    }
    conversion, created = await conversion_repository.insert_conversion(conversion_doc)
    if not created:
        return await finalize("duplicate", 200, conversion_id=existing["conversion_id"] if existing else conversion.get("conversion_id"), canonical=canonical, click=click)

    await audit_record(
        audit_actions.CONVERSION_CREATED, actor_user_id="system",
        metadata={
            "conversion_id": conversion["conversion_id"], "platform": platform,
            "campaign_id": endpoint["campaign_id"], "publisher_id": click["publisher_id"],
            "event": conversion["event"], "payout": payout,
        },
    )

    # Part 9 — earning creation. Best-effort like webhook dispatch below:
    # a Postgres outage must never block Mongo-side conversion recording
    # (that's operational visibility, separate from financial truth), but
    # a failure here is NOT silently swallowed — it's audited so it can be
    # reconciled, since a lost earning is a real financial bug, not a
    # cosmetic one.
    if payout is not None and not awaits_report:
        try:
            from app.services import financial_service

            await financial_service.create_earning_for_conversion(
                conversion_id=conversion["conversion_id"],
                publisher_id=click["publisher_id"],
                manager_id=click.get("manager_id"),
                campaign_id=endpoint["campaign_id"],
                payout=payout,
                request_id=request_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Earning creation failed for conversion %s: %s", conversion["conversion_id"], exc)
            await audit_record(
                audit_actions.EARNING_CREATION_FAILED, actor_user_id="system",
                metadata={"conversion_id": conversion["conversion_id"], "error": str(exc)},
            )

    # Webhook fan-out (Part 10) — subscribed integrations receive the event
    # with an HMAC signature; failures are logged, never fatal here.
    try:
        from app.services import webhook_service

        await webhook_service.dispatch_event("conversion.created", {
            "event": "conversion.created",
            "conversion_id": conversion["conversion_id"],
            "campaign_id": endpoint["campaign_id"],
            "publisher_id": click["publisher_id"],
            "event_name": conversion["event"],
            "status": conversion.get("status"),
            "payout": conversion.get("payout"),
            "currency": conversion.get("currency"),
            "digisnr_click_id": conversion["digisnr_click_id"],
            "external_conversion_id": conversion.get("external_conversion_id"),
            "occurred_at": conversion["conversion_created_at"],
        })
    except Exception as exc:  # noqa: BLE001
        logger.error("webhook dispatch failed: %s", exc)

    # Outbound publisher postback (spec §17) — publisher's own config + the
    # click's preserved parameters. Never blocks conversion acceptance.
    try:
        await postback_service.deliver_publisher_postback(conversion, click)
    except Exception as exc:  # noqa: BLE001 — delivery failure is logged, never fatal
        logger.error("outbound postback delivery failed: %s", exc)

    return await finalize("processed", 200, conversion_id=conversion["conversion_id"], canonical=canonical, click=click)
