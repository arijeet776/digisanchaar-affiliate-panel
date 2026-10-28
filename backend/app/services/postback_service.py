"""Postback management: Super Admin inbound endpoints, publisher outbound
configs (versioned, spec §20), and outbound delivery with SSRF protection,
retries (1 + 3 = 4 attempts, spec §19/§34) and manual refire."""
import asyncio
import ipaddress
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from app.core import audit_actions
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.db import campaign_repository, conversion_repository
from app.db.mongodb import get_database
from app.db.audit_repository import record as audit_record
from app.services import postback_adapters
from app.services.macro_engine import PUBLISHER_MACRO_KEYS, macros_present, substitute_macros

logger = logging.getLogger(__name__)

_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_RETRY_BACKOFF = [0, 0.5, 1.0, 2.0]  # initial + 3 retries = 4 attempts total


def validate_outbound_url(raw: str) -> str:
    """SSRF + safety guard for publisher postback URLs (spec §22/§34)."""
    candidate = (raw or "").strip()
    if not candidate:
        raise ValidationAppError("Postback URL is required")
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        raise ValidationAppError("Postback URL is not valid") from exc
    if parts.scheme.lower() not in ("https", "http"):
        raise ValidationAppError("Postback URL must use http or https")
    if parts.username or parts.password:
        raise ValidationAppError("Postback URL must not contain credentials")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValidationAppError("Postback URL must include a host")
    if host in _BLOCKED_HOSTS:
        raise ValidationAppError("Postback URL host is not allowed")
    from app.core.net_safety import UnsafeDestination, check_literal_host

    try:
        check_literal_host(host)  # non-public IP literals and numeric spellings (2130706433, 0x7f.1, ::ffff:127.0.0.1)
    except UnsafeDestination as exc:
        raise ValidationAppError("Postback URL host is not allowed") from exc
    unknown = [m for m in macros_present(candidate) if m not in PUBLISHER_MACRO_KEYS]
    if unknown:
        raise ValidationAppError(f"Unsupported macros: {', '.join(sorted(set(unknown)))}")
    return candidate


async def create_endpoint(campaign_id: str, platform: str, actor_user_id: str) -> dict:
    if platform not in ("trackier", "offer18", "custom"):
        raise ValidationAppError(f"Unsupported platform: {platform}")
    campaign = await campaign_repository.get_campaign(campaign_id)
    if campaign is None:
        raise NotFoundError("Campaign not found")
    if campaign["status"] == "purged":
        raise ConflictError("Purged campaigns cannot receive postbacks")
    doc = await conversion_repository.create_endpoint(campaign_id, platform, actor_user_id)
    await audit_record(
        audit_actions.POSTBACK_ENDPOINT_CREATED, actor_user_id=actor_user_id,
        metadata={"endpoint_id": doc["endpoint_id"], "campaign_id": campaign_id, "platform": platform},
    )
    return doc


async def set_endpoint_status(endpoint_id: str, status: str, actor_user_id: str) -> dict:
    endpoint = await conversion_repository.get_endpoint(endpoint_id)
    if endpoint is None:
        raise NotFoundError("Endpoint not found")
    updated = await conversion_repository.set_endpoint_status(endpoint_id, status)
    if status == "disabled":
        await audit_record(
            audit_actions.POSTBACK_ENDPOINT_DISABLED, actor_user_id=actor_user_id,
            metadata={"endpoint_id": endpoint_id, "campaign_id": endpoint["campaign_id"]},
        )
    return updated


async def campaign_mapping(campaign_id: str) -> dict:
    """The campaign's macro mapping (click id carrier + advertiser parameter names)."""
    campaign = await campaign_repository.get_campaign(campaign_id)
    config = (await campaign_repository.get_current_config(campaign)) if campaign else None
    config = config or {}
    return {k: config.get(k) for k in ("click_id_param", "advertiser_click_id_param", "campaign_title_param", "event_param", "extra_click_id_params")}


def build_advertiser_postback_url(inbound_url: str, platform: str, mapping: dict | None) -> str:
    """The URL the Super Admin pastes into the advertiser panel. Each parameter
    is `name={name}` — the advertiser's own macro of the same name — and the
    parameter that carried the DigiSNR click id outbound is always first, so
    the id returns through the very same macro."""
    mapping = mapping or {}
    names = [mapping.get(k) for k in ("click_id_param", "advertiser_click_id_param", "event_param", "campaign_title_param")]
    names = [n for n in names if n]
    if not mapping.get("click_id_param"):  # campaign created before macro mapping existed
        names = list(postback_adapters.PLATFORM_METADATA.get(platform, {}).get("required", []))
    seen, pairs = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            pairs.append(f"{n}={{{n}}}")
    return inbound_url + ("?" + "&".join(pairs) if pairs else "")


def serialize_endpoint(doc: dict, base_url: str, mapping: dict | None = None) -> dict:
    """The token appears ONLY here, at creation time, for the admin to copy.
    List responses exclude it (endpoint list = management view, not a secret leak)."""
    return {
        "endpoint_id": doc["endpoint_id"],
        "campaign_id": doc["campaign_id"],
        "platform": doc["platform"],
        "status": doc["status"],
        "received_count": doc.get("received_count", 0),
        "failure_count": doc.get("failure_count", 0),
        "last_received_at": doc.get("last_received_at"),
        "created_at": doc["created_at"],
        "inbound_url": f"{base_url}api/v1/postback/inbound/{doc['platform']}/{doc['token']}",
        "advertiser_postback_url": build_advertiser_postback_url(
            f"{base_url}api/v1/postback/inbound/{doc['platform']}/{doc['token']}", doc["platform"], mapping),
    }


def serialize_endpoint_safe(doc: dict) -> dict:
    return {
        "endpoint_id": doc["endpoint_id"],
        "campaign_id": doc["campaign_id"],
        "platform": doc["platform"],
        "status": doc["status"],
        "received_count": doc.get("received_count", 0),
        "failure_count": doc.get("failure_count", 0),
        "last_received_at": doc.get("last_received_at"),
        "created_at": doc["created_at"],
    }


_SENSITIVE_PARAM = re.compile(r"(token|secret|key|pass|pwd|sig|auth|credential)", re.I)


def safe_url(url: str | None) -> str | None:
    """Presentation-safe URL for logs: values of secret-looking query
    parameters are masked. The stored URL (used for re-fire) is untouched."""
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[unparseable url]"
    if not parts.query:
        return url
    masked = []
    for pair in parts.query.split("&"):
        name, sep, value = pair.partition("=")
        masked.append(f"{name}=***" if sep and value and _SENSITIVE_PARAM.search(name) else pair)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(masked), parts.fragment))


async def save_publisher_config(publisher_id: str, campaign_id: str | None, url: str, actor_user_id: str,
                                enabled: bool = True) -> dict:
    validated = validate_outbound_url(url)
    version = await conversion_repository.next_config_version(publisher_id, campaign_id)
    doc = await conversion_repository.insert_config_version({
        "publisher_id": publisher_id,
        "campaign_id": campaign_id,
        "url_template": validated,
        "macros_selected": sorted(set(macros_present(validated))),
        "version": version,
        "enabled": bool(enabled),
        "deleted": False,
        "created_by": actor_user_id,
    })
    await audit_record(
        audit_actions.GLOBAL_POSTBACK_SAVED if campaign_id is None else audit_actions.PUBLISHER_POSTBACK_CONFIG_SAVED,
        actor_user_id=actor_user_id,
        # URL itself is not logged (may carry the publisher's own secrets).
        metadata={"publisher_id": publisher_id, "campaign_id": campaign_id, "version": version,
                  "enabled": bool(enabled), "macros": doc["macros_selected"]},
    )
    return doc


async def delete_global_config(publisher_id: str, actor_user_id: str) -> bool:
    """Soft delete: a new version flagged deleted/disabled. Version history is
    preserved (no destructive delete); nothing is sent afterwards."""
    latest = await conversion_repository.get_latest_global_config(publisher_id)
    if latest is None or latest.get("deleted"):
        return False
    version = await conversion_repository.next_config_version(publisher_id, None)
    await conversion_repository.insert_config_version({
        "publisher_id": publisher_id, "campaign_id": None, "url_template": "", "macros_selected": [],
        "version": version, "enabled": False, "deleted": True, "created_by": actor_user_id,
    })
    await audit_record(audit_actions.GLOBAL_POSTBACK_DELETED, actor_user_id=actor_user_id,
                       metadata={"publisher_id": publisher_id, "version": version})
    return True


def _fmt_payout(value) -> str | None:
    if value is None:
        return None
    try:
        return ("%.2f" % float(value)).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return None


def build_outbound_values(conversion: dict, click: dict, campaign_name: str | None = None) -> dict:
    """Values a PUBLISHER macro can resolve to - from stored click/conversion
    data only. Advertiser revenue / original rate / margin and the internal
    UTM + platform sub-id mappings are deliberately absent (they resolve
    blank even if an old template still contains them). Missing => blank."""
    when = conversion.get("conversion_created_at") or datetime.now(timezone.utc)
    country = click.get("country")
    values: dict = {
        "click_id": conversion["digisnr_click_id"],
        "digisnr_click_id": conversion["digisnr_click_id"],
        "campaign_id": conversion.get("campaign_id"),
        "campaign_name": campaign_name,
        "publisher_id": conversion.get("publisher_id"),
        "event": conversion.get("event"),
        "status": conversion.get("status"),
        "payout": _fmt_payout(conversion.get("payout")),
        "date": when.strftime("%Y-%m-%d") if hasattr(when, "strftime") else None,
        "date_time": when.isoformat() if hasattr(when, "isoformat") else None,
        "ip": click.get("ip"),
        "country": country,
        "country_code": click.get("country_code") or (country if isinstance(country, str) and len(country) == 2 else None),
        "state": click.get("state"),
        "city": click.get("city"),
    }
    original = click.get("original_params") or {}
    for i in range(1, 11):
        values[f"p{i}"] = original.get(f"p{i}")
    return values


async def _http_get(url: str) -> tuple[int | None, str | None, str | None]:
    """Single delivery attempt — isolated so tests can substitute it."""
    import httpx

    from app.core.net_safety import UnsafeDestination, assert_public_destination

    try:
        await assert_public_destination(url)  # resolves the host: private/loopback/metadata targets are refused at send time
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            resp = await client.get(url)
            return resp.status_code, resp.text[:200], None
    except UnsafeDestination:
        return None, None, "destination not allowed"
    except Exception as exc:  # noqa: BLE001 — network errors become attempt failures
        return None, None, str(exc)[:200]


async def deliver_publisher_postback(conversion: dict, click: dict) -> dict | None:
    config = await conversion_repository.get_postback_config(
        conversion["publisher_id"], conversion["campaign_id"]
    )
    if config is None:
        return None
    # One delivery per conversion: a (re)processed conversion must never fan
    # out a second time just because both Global and campaign configs exist.
    existing = await get_database()["outbound_postbacks"].find_one({"conversion_id": conversion["conversion_id"]})
    if existing is not None:
        return existing
    campaign = await campaign_repository.get_campaign(conversion["campaign_id"])
    campaign_name = campaign["summary"]["name"] if campaign else None
    url, macros_used = substitute_macros(config["url_template"], build_outbound_values(conversion, click, campaign_name))

    attempts = []
    final_status = "failed"
    for index, backoff in enumerate(_RETRY_BACKOFF):
        if backoff:
            await asyncio.sleep(backoff)
        _t0 = asyncio.get_event_loop().time()
        http_status, response_excerpt, error = await _http_get(url)
        attempts.append({
            "latency_ms": int((asyncio.get_event_loop().time() - _t0) * 1000),
            "attempt": index + 1,
            "sent_at": datetime.now(timezone.utc),
            "http_status": http_status,
            "response": response_excerpt,
            "error": error,
        })
        if http_status is not None and 200 <= http_status < 400:
            final_status = "delivered"
            break

    return await conversion_repository.log_outbound({
        "conversion_id": conversion["conversion_id"],
        "publisher_id": conversion["publisher_id"],
        "campaign_id": conversion["campaign_id"],
        "event": conversion.get("event"),
        "status": conversion.get("status"),
        "url": url,
        "macros_used": macros_used,
        "config_version": config["version"],
        "config_scope": "campaign" if config.get("campaign_id") else "global",
        "attempts": attempts,
        "attempt_count": len(attempts),
        "final_status": final_status,
    })


async def refire_outbound(outbound_id: str, actor_user_id: str) -> dict:
    """Manual refire (spec §19) — audited, and only meaningful for a
    previously failed/exhausted delivery."""
    log = await conversion_repository.get_outbound(outbound_id)
    if log is None:
        raise NotFoundError("Outbound postback not found")
    http_status, response_excerpt, error = await _http_get(log["url"])
    attempts = list(log.get("attempts", []))
    attempts.append({
        "attempt": len(attempts) + 1,
        "sent_at": datetime.now(timezone.utc),
        "http_status": http_status,
        "response": response_excerpt,
        "error": error,
        "manual": True,
    })
    delivered = http_status is not None and 200 <= http_status < 400
    from app.db.mongodb import get_database

    await get_database()["outbound_postbacks"].update_one(
        {"outbound_id": outbound_id},
        {"$set": {
            "attempts": attempts,
            "attempt_count": len(attempts),
            "final_status": "delivered" if delivered else "failed",
            "refired_by": actor_user_id,
            "refired_at": datetime.now(timezone.utc),
        }},
    )
    await audit_record(
        audit_actions.OUTBOUND_POSTBACK_REFIRED, actor_user_id=actor_user_id,
        metadata={"outbound_id": outbound_id, "conversion_id": log["conversion_id"], "result": "delivered" if delivered else "failed"},
    )
    updated = await conversion_repository.get_outbound(outbound_id)
    return updated


async def send_test_postback(publisher_id: str, campaign_id: str | None, url: str) -> dict:
    """One-shot test delivery of a publisher's own URL with sample values.
    Same SSRF guard as the real config; nothing is logged as a conversion."""
    validated = validate_outbound_url(url)
    now = datetime.now(timezone.utc)
    # Clearly-labelled TEST values: nothing is stored as a conversion.
    sample = {
        "click_id": "DGSNR-TEST", "digisnr_click_id": "DGSNR-TEST", "campaign_id": "TEST",
        "campaign_name": "Test Campaign", "publisher_id": publisher_id, "event": "test",
        "status": "success", "payout": "0", "date": now.strftime("%Y-%m-%d"), "date_time": now.isoformat(),
    }
    final, _used = substitute_macros(validated, sample)
    t0 = asyncio.get_event_loop().time()
    http_status, excerpt, error = await _http_get(final)
    return {"http_status": http_status, "error": error, "response": excerpt,
            "latency_ms": int((asyncio.get_event_loop().time() - t0) * 1000), "url": final}
