"""Offline event reporting.

Some advertisers settle an event (e.g. a loan disbursal) only in a report they
send later — no postback ever fires. For events configured as `offline`:

  * the admin/manager pastes the DigiSNR click ids that appear in the
    advertiser's report and approves them → a conversion is created, the
    publisher's wallet is credited (same earning path as every other
    conversion) and the publisher's own postback fires;
  * clicks that did not appear stay Pending, or are marked Rejected.

Reuses conversion_review_service for the actual state change so earnings,
reversals and audit trails behave exactly like company-report reviews.
Rejected is final (existing ledger rule).
"""
import logging
from datetime import datetime, timezone

from app.core.enums import ConversionApprovalStatus as S, Role
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.core.rbac import CurrentUser
from app.db import campaign_repository, conversion_repository, manager_repository
from app.db.mongodb import get_database
from app.services import conversion_review_service, postback_service
from app.services.conversion_service import _resolve_payout

logger = logging.getLogger(__name__)
MAX_IDS = 500
PLATFORM = "offline"


def _val(x) -> str:
    return str(getattr(x, "value", x))


async def _manager_scope(user: CurrentUser) -> str | None:
    if user.role != Role.MANAGER:
        return None
    m = await manager_repository.get_manager_by_user_id(user.user_id)
    if m is None:
        raise ForbiddenError("Manager profile not found")
    return m["manager_id"]


async def _require_offline_event(campaign_id: str, event_name: str) -> dict:
    campaign = await campaign_repository.get_campaign(campaign_id)
    if campaign is None:
        raise NotFoundError("Campaign not found")
    config = await campaign_repository.get_current_config(campaign) or {}
    for ev in config.get("events", []):
        if ev["event_name"].lower() == event_name.lower():
            if _val(ev.get("completion_source")) != "offline":
                raise ValidationAppError(f"'{ev['event_name']}' is an online event — it is settled by postback")
            return campaign
    raise NotFoundError("Event not found on this campaign")


def _key(click_id: str, event_name: str) -> str:
    return f"{PLATFORM}|{click_id}|{event_name.lower()}"


async def _ensure_conversion(click: dict, campaign_id: str, event_name: str) -> dict:
    existing = await get_database()["conversions"].find_one({"idempotency_key": _key(click["digisnr_click_id"], event_name)})
    if existing is not None:
        return existing
    payout, note = await _resolve_payout(campaign_id, event_name)
    doc = {
        "idempotency_key": _key(click["digisnr_click_id"], event_name),
        "platform": PLATFORM,
        "campaign_id": campaign_id,
        "campaign_code": click.get("campaign_code"),
        "publisher_id": click["publisher_id"],
        "publisher_code": click.get("publisher_code"),
        "manager_id": click.get("manager_id"),
        "link_id": click.get("link_id"),
        "digisnr_click_id": click["digisnr_click_id"],
        "external_click_id": click.get("external_click_id"),
        "event": event_name,
        "goal": event_name,
        "status": "pending",
        "payout": payout,
        "payout_note": note,
        "approval_status": S.PENDING_REPORT.value,
        "sub_ids": {}, "utm": {},
        "click_created_at": click.get("click_created_at"),
        "postback_received_at": datetime.now(timezone.utc),
        "config_version": click.get("config_version"),
    }
    conversion, _created = await conversion_repository.insert_conversion(doc)
    return conversion


async def _load_click(user: CurrentUser, campaign_id: str, click_id: str) -> dict | None:
    click = await conversion_repository.get_click(click_id)
    if click is None or click["campaign_id"] != campaign_id:
        return None
    mgr = await _manager_scope(user)
    if mgr is not None and click.get("manager_id") != mgr:
        return None
    return click


async def offline_campaigns(user: CurrentUser) -> list[dict]:
    """Campaigns that have at least one offline event (for the dropdown)."""
    items, _ = await campaign_repository.list_campaigns(None, None, None, 0, 200)
    out = []
    for c in items:
        config = await campaign_repository.get_current_config(c) or {}
        events = [e["event_name"] for e in config.get("events", []) if _val(e.get("completion_source")) == "offline"]
        if events:
            out.append({"campaign_id": c["campaign_id"], "name": c["summary"]["name"], "events": events})
    return out


async def approve_clicks(user: CurrentUser, campaign_id: str, event_name: str, click_ids: list[str],
                         request_id: str | None = None) -> dict:
    await _require_offline_event(campaign_id, event_name)
    ids = list(dict.fromkeys(i.strip() for i in click_ids if i and i.strip()))[:MAX_IDS]
    if not ids:
        raise ValidationAppError("Enter at least one DigiSNR click id")
    results = []
    for cid in ids:
        click = await _load_click(user, campaign_id, cid)
        if click is None:
            results.append({"click_id": cid, "result": "not_found"})
            continue
        try:
            conv = await _ensure_conversion(click, campaign_id, event_name)
            current = conv.get("approval_status") or S.CONFIRMED.value
            if current == S.CONFIRMED.value:
                results.append({"click_id": cid, "result": "already_approved"})
                continue
            if current == S.REJECTED.value:
                results.append({"click_id": cid, "result": "rejected_final"})
                continue
            await conversion_review_service.record_outcome(
                user, conv["conversion_id"], True, "Offline advertiser report", request_id)
            try:  # publisher's own postback — best effort, never blocks the approval
                await postback_service.deliver_publisher_postback({**conv, "status": "approved"}, click)
            except Exception as exc:  # noqa: BLE001
                logger.error("offline publisher postback failed: %s", exc)
            results.append({"click_id": cid, "result": "approved"})
        except ConflictError as exc:
            results.append({"click_id": cid, "result": "error", "detail": str(exc)})
    return {"results": results, "approved": sum(1 for r in results if r["result"] == "approved")}


async def mark_click(user: CurrentUser, campaign_id: str, event_name: str, click_id: str, status: str,
                     request_id: str | None = None) -> dict:
    await _require_offline_event(campaign_id, event_name)
    click = await _load_click(user, campaign_id, click_id)
    if click is None:
        raise NotFoundError("Click not found")
    conv = await _ensure_conversion(click, campaign_id, event_name)
    current = conv.get("approval_status") or S.CONFIRMED.value
    if status == "rejected":
        await conversion_review_service.record_outcome(
            user, conv["conversion_id"], False, "Not in advertiser report", request_id)
        return {"click_id": click_id, "status": "rejected"}
    if current == S.CONFIRMED.value:
        raise ConflictError("Already approved — reject it to reverse the earning")
    if current == S.REJECTED.value:
        raise ConflictError("Rejected is final; use a financial adjustment to correct")
    return {"click_id": click_id, "status": "pending"}


async def list_offline_clicks(user: CurrentUser, campaign_id: str, event_name: str,
                              search: str | None, page: int, page_size: int) -> dict:
    await _require_offline_event(campaign_id, event_name)
    page_size = max(1, min(page_size, 100))
    query: dict = {"campaign_id": campaign_id}
    mgr = await _manager_scope(user)
    if mgr:
        query["manager_id"] = mgr
    if search:
        query["digisnr_click_id"] = search.strip()
    db = get_database()
    total = await db["clicks"].count_documents(query)
    clicks = await (db["clicks"].find(query).sort("click_created_at", -1)
                    .skip((page - 1) * page_size).limit(page_size).to_list(length=page_size))
    convs = await db["conversions"].find(
        {"campaign_id": campaign_id, "platform": PLATFORM}).limit(5000).to_list(length=5000)
    state = {c["digisnr_click_id"]: c.get("approval_status") for c in convs if (c.get("event") or "").lower() == event_name.lower()}
    label = {S.CONFIRMED.value: "approved", S.REJECTED.value: "rejected"}
    items = [{
        "click_id": c["digisnr_click_id"], "publisher_id": c["publisher_id"],
        "clicked_at": c.get("click_created_at"),
        "status": label.get(state.get(c["digisnr_click_id"]), "pending"),
    } for c in clicks]
    return {"items": items, "total": total}
