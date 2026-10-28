"""
Part 5 tracking engine — link generation + the public click pipeline.

Click request order (master spec §24, non-negotiable):
  rate limit (endpoint dependency)
  → blocked-IP / security check
  → campaign validation
  → publisher/link validation
  → campaign lifecycle validation
  → cap validation
  → click creation (immutable DGSNR id, full parameter snapshot)
  → advertiser redirect (whitelisted macro substitution only)

A blocked request creates NO click, NO attribution, NO redirect (§24).
"""
import logging
from datetime import datetime, timezone

from bson import ObjectId

from app.core import audit_actions
from app.core.enums import AccountStatus, CampaignStatus, FraudBlockStatus, PauseReasonType, Role
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.rbac import CurrentUser
from app.db import (
    blocked_ip_repository,
    campaign_repository,
    manager_repository,
    publisher_repository,
    tracking_repository,
)
from app.db.audit_repository import record as audit_record
from app.db.mongodb import get_database
from app.services import settings_service
from app.services.campaign_service import assert_campaign_is_traffic_live
from app.services.macro_engine import substitute_macros

logger = logging.getLogger(__name__)

# The ONLY message a blocked request ever receives (spec §37) — never the
# internal reason, score, or rule.
BLOCKED_PUBLIC_MESSAGE = (
    "Access Restricted — Suspicious traffic activity was detected. "
    "Please contact support if you believe this was a mistake."
)
LINK_NOT_FOUND_MESSAGE = "Link not found."
LINK_UNAVAILABLE_MESSAGE = "This link is no longer available."
CAP_REACHED_MESSAGE = "This campaign is temporarily unavailable."

_ALLOWED_CLICK_PARAMS = {f"p{i}" for i in range(1, 11)} | {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
}
MAX_PARAM_VALUE_LENGTH = 200
MAX_USER_AGENT_LENGTH = 300


def sanitize_click_params(query_params) -> dict[str, str]:
    """spec §29 — allowlist p1–p10 + UTM parameters; unknown parameters are
    safely ignored, repeated parameters resolve last-wins (defined policy),
    values are length-capped and stripped of control characters. Values are
    DATA, never code — they are only ever re-emitted URL-encoded (macro engine).
    """
    clean: dict[str, str] = {}
    for key, value in query_params.multi_items() if hasattr(query_params, "multi_items") else query_params.items():
        normalized = key.lower()
        if normalized not in _ALLOWED_CLICK_PARAMS:
            continue
        text = "".join(ch for ch in str(value) if ch.isprintable())[:MAX_PARAM_VALUE_LENGTH]
        clean[normalized] = text
    return clean


def inject_query_param(url: str, name: str, value: str) -> str:
    """Set `name=value` on the URL's query, replacing any existing value (and
    any left-over `{macro}` placeholder) so the DigiSNR click id always lands
    in exactly the parameter the Super Admin chose for this campaign."""
    from urllib.parse import quote, urlsplit, urlunsplit

    parts = urlsplit(url)
    kept = [pair for pair in parts.query.split("&") if pair and pair.partition("=")[0].lower() != name.lower()]
    kept.append(f"{name}={quote(value, safe='')}")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(kept), parts.fragment))


async def _publisher_account_active(publisher: dict) -> bool:
    db = get_database()
    user = await db["users"].find_one({"_id": ObjectId(publisher["user_id"])})
    return user is not None and user["account_status"] == AccountStatus.ACTIVE.value


async def serialize_link(doc: dict) -> dict:
    base = await settings_service.get_active_tracking_base_url()
    campaign = await campaign_repository.get_campaign(doc["campaign_id"])
    publisher = await publisher_repository.get_publisher_by_publisher_id(doc["publisher_id"])
    click_count = await tracking_repository.count_clicks_for_link(doc["link_id"])
    return {
        "link_id": doc["link_id"],
        "public_code": doc["public_code"],
        "campaign_id": doc["campaign_id"],
        "campaign_code": doc["campaign_code"],
        "campaign_name": campaign["summary"]["name"] if campaign else None,
        "publisher_id": doc["publisher_id"],
        "publisher_code": doc["publisher_code"],
        "publisher_name": publisher.get("display_name") if publisher else None,
        "manager_id": doc["manager_id"],
        "status": doc["status"],
        "tracking_url": (
            settings_service.build_tracking_url_from_base(base, doc["campaign_code"], doc["public_code"])
            if base
            else None
        ),
        "click_count": click_count,
        "created_at": doc["created_at"],
    }


async def generate_tracking_link(campaign_id: str, publisher_id: str, actor: CurrentUser) -> dict:
    if actor.role == Role.PUBLISHER:
        raise ForbiddenError("Publishers cannot generate tracking links")

    campaign = await campaign_repository.get_campaign(campaign_id)
    if campaign is None:
        raise NotFoundError("Campaign not found")
    # Only ACTIVE campaigns produce links — paused/ended/purged rejected (spec §13/§16)
    assert_campaign_is_traffic_live(campaign)

    publisher = await publisher_repository.get_publisher_by_publisher_id(publisher_id)
    if publisher is None:
        raise NotFoundError("Publisher not found")
    if not await _publisher_account_active(publisher):
        raise ConflictError("Publisher account is not active")

    if actor.role == Role.MANAGER:
        manager_profile = await manager_repository.get_manager_by_user_id(actor.user_id)
        if manager_profile is None or publisher["manager_id"] != manager_profile["manager_id"]:
            raise ForbiddenError("You do not have authority over this Publisher")

    return await _create_link(campaign, publisher, actor.user_id)


async def generate_link_for_access(campaign_id: str, publisher_id: str, created_by: str) -> dict:
    """Used by the campaign-access flow (publisher self-serve for
    PROMOTE_IMMEDIATELY campaigns, or after a manager/admin approval). The
    caller has already authorised the access; the same campaign-live,
    account-active and tracking-domain checks still apply."""
    campaign = await campaign_repository.get_campaign(campaign_id)
    if campaign is None:
        raise NotFoundError("Campaign not found")
    assert_campaign_is_traffic_live(campaign)
    publisher = await publisher_repository.get_publisher_by_publisher_id(publisher_id)
    if publisher is None:
        raise NotFoundError("Publisher not found")
    if not await _publisher_account_active(publisher):
        raise ConflictError("Publisher account is not active")
    return await _create_link(campaign, publisher, created_by)


async def _create_link(campaign: dict, publisher: dict, created_by: str) -> dict:
    campaign_id = campaign["campaign_id"]
    publisher_id = publisher["publisher_id"]
    base_url = await settings_service.get_active_tracking_base_url()
    if not base_url:
        raise ConflictError(
            "Configure the tracking domain first (System Settings → Domain & Tracking)"
        )

    # Idempotent: one active link per campaign+publisher (spec §14 spirit).
    existing = await tracking_repository.find_active_link(campaign_id, publisher_id)
    if existing is not None:
        return await serialize_link(existing)

    campaign_code = await tracking_repository.ensure_campaign_code(campaign_id)
    publisher_code = await tracking_repository.ensure_publisher_code(publisher_id)
    doc = await tracking_repository.create_tracking_link(
        {
            "campaign_id": campaign_id,
            "campaign_code": campaign_code,
            "publisher_id": publisher_id,
            "publisher_code": publisher_code,
            "manager_id": publisher["manager_id"],
            "config_version": campaign["current_config_version"],
            "status": "active",
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc),
        }
    )
    await audit_record(
        audit_actions.TRACKING_LINK_CREATED,
        actor_user_id=created_by,
        metadata={
            "link_id": doc["link_id"],
            "campaign_id": campaign_id,
            "publisher_id": publisher_id,
            "campaign_code": campaign_code,
            "public_code": doc["public_code"],
        },
    )
    return await serialize_link(doc)


async def list_links(actor: CurrentUser) -> list[dict]:
    if actor.role == Role.SUPER_ADMIN:
        docs = await tracking_repository.list_links()
    elif actor.role == Role.MANAGER:
        profile = await manager_repository.get_manager_by_user_id(actor.user_id)
        if profile is None:
            raise ForbiddenError("Manager profile not found for current user")
        docs = await tracking_repository.list_links(manager_id=profile["manager_id"])
    else:  # PUBLISHER — own links only
        profile = await publisher_repository.get_publisher_by_user_id(actor.user_id)
        if profile is None:
            raise ForbiddenError("Publisher profile not found for current user")
        docs = await tracking_repository.list_links(publisher_id=profile["publisher_id"])
    return [await serialize_link(doc) for doc in docs]


async def _auto_pause_for_cap(campaign: dict, cap_kind: str) -> None:
    """Cap auto-pause (spec §33): reason recorded, audited, atomic."""
    reason = "Daily cap reached" if cap_kind == "daily" else "Overall cap reached"
    updated = await campaign_repository.atomic_status_transition(
        campaign["campaign_id"], [CampaignStatus.ACTIVE], CampaignStatus.PAUSED,
        reason=reason, reason_type=PauseReasonType.CAP_REACHED,
    )
    if updated is not None:
        await audit_record(
            audit_actions.CAMPAIGN_PAUSED,
            actor_user_id="system",
            reason=reason,
            metadata={"campaign_id": campaign["campaign_id"], "cap": cap_kind, "automatic": True},
        )


async def _is_blocked(ip: str | None) -> bool:
    if not ip:
        return False
    record = await blocked_ip_repository.find_by_ip(ip)
    return record is not None and record["status"] in (
        FraudBlockStatus.BLOCKED.value,
        FraudBlockStatus.PERMANENT_BLOCK.value,
    )


async def process_click(
    campaign_code: str,
    link_code: str,
    query_params,
    client_ips: list[str],
    user_agent: str,
) -> dict:
    """Returns {"action": "redirect"|"reject", ...} — the endpoint translates
    it into a 302 or a minimal public response. Nothing internal leaks."""

    # 1. Blocked-IP / security check — before ANY state change (spec §24).
    for ip in client_ips:
        if await _is_blocked(ip):
            return {"action": "reject", "status": 403, "message": BLOCKED_PUBLIC_MESSAGE}

    # 2. Public codes → internal link (spec §2/§21). Both codes must match,
    # so a link code can never be transplanted onto another campaign.
    link = await tracking_repository.get_link_by_codes(campaign_code, link_code)
    if link is None or link["status"] != "active":
        return {"action": "reject", "status": 404, "message": LINK_NOT_FOUND_MESSAGE}

    # 3. Campaign validation + lifecycle (§13/§16 — purged campaigns die here).
    campaign = await campaign_repository.get_campaign(link["campaign_id"])
    if campaign is None or campaign.get("public_code") != campaign_code:
        return {"action": "reject", "status": 404, "message": LINK_NOT_FOUND_MESSAGE}
    if campaign["status"] != CampaignStatus.ACTIVE.value:
        return {"action": "reject", "status": 410, "message": LINK_UNAVAILABLE_MESSAGE}

    # 4. Publisher validation — the account behind the link must be active.
    publisher = await publisher_repository.get_publisher_by_publisher_id(link["publisher_id"])
    if publisher is None or not await _publisher_account_active(publisher):
        return {"action": "reject", "status": 410, "message": LINK_UNAVAILABLE_MESSAGE}

    config = await campaign_repository.get_current_config(campaign)
    if config is None:
        return {"action": "reject", "status": 410, "message": LINK_UNAVAILABLE_MESSAGE}

    # 5. Cap validation (§33) — before click creation; hitting a cap
    # auto-pauses with reason + audit and rejects the click.
    campaign_id = campaign["campaign_id"]
    overall_cap = config.get("overall_cap")
    if overall_cap is not None:
        if await tracking_repository.count_clicks(campaign_id) >= overall_cap:
            await _auto_pause_for_cap(campaign, "overall")
            return {"action": "reject", "status": 410, "message": CAP_REACHED_MESSAGE}
    daily_cap = config.get("daily_cap")
    if daily_cap is not None:
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        if await tracking_repository.count_clicks(campaign_id, since=day_start) >= daily_cap:
            await _auto_pause_for_cap(campaign, "daily")
            return {"action": "reject", "status": 410, "message": CAP_REACHED_MESSAGE}

    # 6. Click creation — one immutable DGSNR id, full parameter snapshot (§9/§10).
    params = sanitize_click_params(query_params)
    # The parameter carrying OUR click id for this campaign is reserved: if a
    # publisher also sends it, their value is dropped (never stored, never
    # forwarded) so it cannot collide with or spoof the DigiSNR click id.
    reserved = (config.get("click_id_param") or "").lower()
    extras = [str(n).lower() for n in (config.get("extra_click_id_params") or []) if n]
    for name in [reserved, *extras]:
        if name:
            params.pop(name, None)
    click_doc: dict = {
        "campaign_id": campaign_id,
        "campaign_code": campaign_code,
        "publisher_id": link["publisher_id"],
        "publisher_code": link["publisher_code"],
        "manager_id": link["manager_id"],
        "link_id": link["link_id"],
        "link_code": link_code,
        "original_params": params,
        "ip": client_ips[0] if client_ips else None,
        "user_agent": user_agent[:MAX_USER_AGENT_LENGTH] if user_agent else None,
        "country": None,  # geo intelligence lands with the conversion part
        "state": None,
        "city": None,
        "source_click_id": None,      # populated by inbound postbacks (Part 6)
        "external_click_id": None,
        "agency_click_id": None,
        "config_version": campaign["current_config_version"],
        "click_created_at": datetime.now(timezone.utc),
    }
    for i in range(1, 11):
        key = f"p{i}"
        if key in params:
            click_doc[f"sub_id_{i}"] = params[key]
    for utm in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"):
        if utm in params:
            click_doc[utm] = params[utm]
    click = await tracking_repository.insert_click(click_doc)
    click_id = click["digisnr_click_id"]

    # A publisher may put the literal {click_id} into any custom parameter
    # (e.g. ?p1={click_id}); it is replaced with OUR unique click id, never
    # an upstream one, and the stored snapshot is updated to match.
    expanded = {k: (v.replace("{click_id}", click_id).replace("%7Bclick_id%7D", click_id).replace("%7bclick_id%7d", click_id)
                    if isinstance(v, str) else v) for k, v in params.items()}
    if expanded != params:
        params = expanded
        await tracking_repository.update_click_params(click_id, params)

    # 7. Advertiser redirect — whitelisted macro substitution only (§4).
    destination = config.get("advertiser_tracking_url") or ""
    macro_values: dict[str, object] = {
        "click_id": click_id,
        "digisnr_click_id": click_id,
        "campaign_code": campaign_code,
        "campaign_id": campaign_id,
        "publisher_code": link["publisher_code"],
        "publisher_id": link["publisher_id"],
        "ip": client_ips[0] if client_ips else None,
        "date_time": datetime.now(timezone.utc).isoformat(),
    }
    macro_values.update(params)
    redirect_url, _used = substitute_macros(destination, macro_values)
    if reserved:
        redirect_url = inject_query_param(redirect_url, reserved, click_id)
    for name in (config.get("extra_click_id_params") or []):
        if name:  # same DigiSNR click id also sent in these parameters
            redirect_url = inject_query_param(redirect_url, str(name), click_id)

    return {"action": "redirect", "url": redirect_url, "click_id": click_id}
