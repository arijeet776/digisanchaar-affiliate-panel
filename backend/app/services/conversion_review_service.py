"""Company-report reconciliation of conversions.

A postback only says what the tracker claimed at the time. When the
campaign has a validation window (tracking_window_hours), the advertiser's
final report decides: CONFIRMED creates the publisher earning (Part 9,
idempotent per conversion), REJECTED never earns — or, if a confirmed
conversion is later rejected (chargeback), posts a compensating reversal.
Rejected is terminal: corrections go through a financial adjustment so the
ledger history stays honest.
"""
from datetime import datetime, timezone

from app.core import audit_actions
from app.core.enums import ConversionApprovalStatus as S, Role
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ServiceUnavailableError
from app.core.rbac import CurrentUser
from app.db import conversion_repository, manager_repository
from app.db.audit_repository import record as audit_record
from app.services import financial_service


async def _scope_manager_id(user: CurrentUser) -> str | None:
    if user.role != Role.MANAGER:
        return None
    m = await manager_repository.get_manager_by_user_id(user.user_id)
    if m is None:
        raise ForbiddenError("Manager profile not found")
    return m["manager_id"]


async def list_review(user: CurrentUser, approval_status: str | None, campaign_id: str | None,
                      skip: int, limit: int) -> dict:
    items, total = await conversion_repository.list_for_review(
        await _scope_manager_id(user), approval_status, campaign_id, skip, limit)
    return {"items": items, "total": total}


GROUP_FETCH_CAP = 5000


def _sort_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def group_by_click(convs: list[dict]) -> list[dict]:
    """ONE row per DigiSNR click ID. Each conversion (event) is an entry in `events`.
    The row date is the original click date and does not move when a later event arrives."""
    groups: dict[str, dict] = {}
    for c in convs:
        cid = c["digisnr_click_id"]
        g = groups.get(cid)
        if g is None:
            g = {
                "digisnr_click_id": cid,
                "campaign_id": c.get("campaign_id"),
                "publisher_id": c.get("publisher_id"),
                "manager_id": c.get("manager_id"),
                "date": c.get("click_created_at") or c.get("conversion_created_at") or c.get("postback_received_at"),
                "events": [],
                "total_payout": 0.0,
            }
            groups[cid] = g
        approval = c.get("approval_status") or S.CONFIRMED.value
        g["events"].append({
            "conversion_id": c["conversion_id"],
            "event": c.get("event"),
            "status": c.get("status"),
            "approval_status": approval,
            "payout": c.get("payout"),
            "postback_received_at": c.get("postback_received_at"),
            "conversion_created_at": c.get("conversion_created_at"),
        })
        if approval != S.REJECTED.value and c.get("payout") is not None:
            g["total_payout"] += float(c["payout"])
    out = list(groups.values())
    for g in out:
        g["events"].sort(key=lambda e: _sort_dt(e["conversion_created_at"]))
        g["total_payout"] = round(g["total_payout"], 2)
    out.sort(key=lambda g: _sort_dt(g["date"]), reverse=True)
    return out


async def list_review_grouped(user: CurrentUser, approval_status: str | None, campaign_id: str | None,
                              skip: int, limit: int) -> dict:
    """Same scope and filters as list_review, grouped by click ID and paged over click rows."""
    items, _ = await conversion_repository.list_for_review(
        await _scope_manager_id(user), approval_status, campaign_id, 0, GROUP_FETCH_CAP)
    groups = group_by_click(items)
    return {"items": groups[skip:skip + limit], "total": len(groups)}


async def record_outcome(user: CurrentUser, conversion_id: str, confirm: bool, note: str | None,
                         request_id: str | None = None) -> dict:
    mgr = await _scope_manager_id(user)
    conv = await conversion_repository.get_conversion(conversion_id)
    if conv is None or (mgr is not None and conv.get("manager_id") != mgr):
        raise NotFoundError("Conversion not found")  # no existence leak across managers

    current = conv.get("approval_status") or S.CONFIRMED.value  # legacy rows were earned at postback time
    if confirm:
        if current == S.CONFIRMED.value:
            return {"conversion": conv, "idempotent": True}
        if current == S.REJECTED.value:
            raise ConflictError("Rejected conversions are final; use a financial adjustment to correct")
        if conv.get("payout") is None:
            raise ConflictError("Conversion has no configured payout and cannot be confirmed")
        updated = await conversion_repository.transition_approval(
            conversion_id, [S.PENDING_REPORT.value], S.CONFIRMED.value, user.user_id, note)
        if updated is None:
            raise ConflictError("Conversion was already decided")
        try:
            await financial_service.create_earning_for_conversion(
                conversion_id=conversion_id, publisher_id=conv["publisher_id"], manager_id=conv.get("manager_id"),
                campaign_id=conv["campaign_id"], payout=conv["payout"], request_id=request_id)
        except Exception as exc:  # noqa: BLE001 — never leave CONFIRMED without its earning
            await conversion_repository.transition_approval(
                conversion_id, [S.CONFIRMED.value], S.PENDING_REPORT.value, user.user_id, "earning failed; reverted")
            await audit_record(audit_actions.EARNING_CREATION_FAILED, actor_user_id=user.user_id,
                               metadata={"conversion_id": conversion_id, "error": str(exc)})
            raise ServiceUnavailableError("Could not post the earning; conversion left pending") from exc
        await audit_record(audit_actions.CONVERSION_REPORT_CONFIRMED, actor_user_id=user.user_id,
                           metadata={"conversion_id": conversion_id, "note": note})
        return {"conversion": updated, "idempotent": False}

    # reject
    if current == S.REJECTED.value:
        return {"conversion": conv, "idempotent": True}
    updated = await conversion_repository.transition_approval(
        conversion_id, [S.PENDING_REPORT.value, S.CONFIRMED.value], S.REJECTED.value, user.user_id, note)
    if updated is None:
        raise ConflictError("Conversion was already decided")
    if current == S.CONFIRMED.value:
        await financial_service.reverse_earning(
            conversion_id=conversion_id, reason=note or "Rejected in company report", actor_user_id=user.user_id)
    await audit_record(audit_actions.CONVERSION_REPORT_REJECTED, actor_user_id=user.user_id,
                       metadata={"conversion_id": conversion_id, "note": note, "reversed": current == S.CONFIRMED.value})
    return {"conversion": updated, "idempotent": False}
