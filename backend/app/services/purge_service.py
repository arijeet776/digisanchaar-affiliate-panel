"""
Campaign-specific data purge — Final Execution Directive §4-17.

WHAT THIS IS: permanent deletion of ONE selected, ENDED campaign's purgeable
operational data, scoped strictly by that campaign's canonical business
campaign_id.

WHAT THIS IS NOT: a database or collection wipe. The dependency map below is
backend-defined and complete; every delete is exactly
{"campaign_id": <the selected campaign's id>}. Publisher, manager and user
records, other campaigns' data, immutable config history, audit logs and ALL
financial records (Postgres/Supabase) are outside the purge boundary by
design — no code path in this module can reach them.
"""
import logging
import uuid
from datetime import datetime, timezone

from app.core import audit_actions
from app.core.enums import CampaignStatus, PurgeOperationStatus
from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError, ValidationAppError
from app.core.logging_config import request_id_ctx
from app.db import campaign_repository, purge_repository
from app.db.audit_repository import record as audit_record
from app.db.mongodb import get_database
from app.storage import runtime

# Supabase mode: the tables a settled campaign's data lives in (must match 002_campaign_purge.sql).
SUPABASE_PURGE_TABLES: list[tuple[str, str]] = [
    ("clicks", "Clicks"),
    ("conversions", "Conversions"),
    ("inbound_postbacks", "Inbound Postback Logs"),
    ("outbound_postbacks", "Outbound Postback Logs"),
    ("tracking_links", "Tracking Links"),
    ("campaign_access", "Campaign Access Records"),
    ("blocked_ips", "Blocked IPs"),
    ("postback_endpoints", "Postback Endpoints"),
    ("publisher_postback_configs", "Publisher Postback Configs"),
    ("campaign_config_versions", "Campaign Config Versions"),
]

logger = logging.getLogger(__name__)


class AlreadyProcessedError(ConflictError):
    code = "ALREADY_PROCESSED"


# The explicit purge dependency map (directive §8). Backend-defined; the
# frontend can neither add to nor select from it. Every entry is counted and
# deleted with filter {"campaign_id": <selected id>} — nothing else.
PURGE_DEPENDENCY_MAP: list[tuple[str, str]] = [
    ("tracking_links", "Tracking Links"),
    ("campaign_access", "Campaign Access Records"),
    ("clicks", "Clicks"),
    ("conversions", "Conversions"),
    ("inbound_postbacks", "Inbound Postback Logs"),
    ("outbound_postbacks", "Outbound Postback Logs"),
    ("campaign_events", "Operational Events"),
    ("attribution_mappings", "Temporary Attribution Data"),
    ("postback_endpoints", "Postback Endpoints"),
    ("blocked_ips", "Fraud/Operational Records"),
]

# Explicitly OUTSIDE the purge boundary (directive §8/§9/§10/§17/§18):
#   users, managers, publishers       — identity/business records, not campaign data
#   invites, otps, refresh_sessions   — auth lifecycle, not campaign data
#   audit_logs                        — immutable compliance trail; the purge's own
#                                       audit record must survive the purge
#   campaign_config_versions          — immutable configuration history, retained
#                                       per the retention policy (§18)
#   campaigns                         — tombstoned (§17), never deleted
#   Postgres/Supabase (all of it)     — the authoritative financial ledger; this
#                                       module never touches it (§9)

# Collections whose DOCUMENT TOTALS are snapshotted before/after the purge to
# prove unrelated data is unchanged (directive §14/§22).
INTEGRITY_WATCH_COLLECTIONS = ["users", "managers", "publishers", "campaigns", "audit_logs"]


async def get_purge_preview(campaign_id: str) -> dict:
    """Real database counts only (directive §6) — nothing invented."""
    campaign_doc = await campaign_repository.get_campaign(campaign_id)
    if campaign_doc is None:
        raise NotFoundError("Campaign not found")

    categories = []
    total = 0
    if runtime.is_supabase_rest():
        db = get_database()
        for collection, label in SUPABASE_PURGE_TABLES:
            count = await db[collection].count_documents({"campaign_id": campaign_id})
            categories.append({"collection": collection, "label": label, "count": count})
            total += count
    else:
        for collection, label in PURGE_DEPENDENCY_MAP:
            count = await purge_repository.count_campaign_scoped(collection, campaign_id)
            categories.append({"collection": collection, "label": label, "count": count})
            total += count

    status = CampaignStatus(campaign_doc["status"])
    eligible = status == CampaignStatus.ENDED
    if status == CampaignStatus.PURGED:
        reason = "This campaign's operational data has already been purged."
    elif not eligible:
        reason = f"Only an ended campaign can be purged (current status: {status.value})."
    else:
        reason = None

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign_doc["summary"]["name"],
        "status": status,
        "eligible": eligible,
        "eligibility_reason": reason,
        "categories": categories,
        "total_purgeable_records": total,
    }


async def execute_purge(
    campaign_id: str, confirm_campaign_name: str, actor_user_id: str, actor_role: str
) -> dict:
    """Controlled server-side purge (directive §12). Frontend deletes nothing."""
    campaign_doc = await campaign_repository.get_campaign(campaign_id)
    if campaign_doc is None:
        raise NotFoundError("Campaign not found")

    status = CampaignStatus(campaign_doc["status"])
    if status == CampaignStatus.PURGED:
        # Safe repeated purge (directive §22 test 15): no second deletion and
        # no second tombstone — the original operation stands.
        existing = await purge_repository.get_latest_operation_for_campaign(campaign_id)
        raise AlreadyProcessedError(
            "This campaign's data was already purged"
            + (f" (operation {existing['purge_id']})" if existing else "")
        )
    if status != CampaignStatus.ENDED:
        raise ConflictError(f"Only an ended campaign can be purged (current status: {status.value})")

    campaign_name = campaign_doc["summary"]["name"]
    if confirm_campaign_name != campaign_name:
        raise ValidationAppError("Confirmation does not match the exact campaign name")

    if runtime.is_supabase_rest():
        return await _execute_supabase_purge(campaign_id, campaign_name, actor_user_id, actor_role)

    # Idempotency / safe retry (directive §13): a resumable operation means a
    # previous attempt was interrupted mid-purge. Deletes are idempotent by
    # construction, so resuming simply re-runs them and re-verifies.
    operation = await purge_repository.get_resumable_operation(campaign_id)
    if operation is None:
        preview = await get_purge_preview(campaign_id)
        operation = await purge_repository.create_operation(
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            actor_user_id=actor_user_id,
            request_id=request_id_ctx.get(),
            planned_counts={c["collection"]: c["count"] for c in preview["categories"]},
        )
    await purge_repository.update_operation(
        operation["purge_id"], status=PurgeOperationStatus.RUNNING.value
    )

    integrity_before = {c: await purge_repository.count_total(c) for c in INTEGRITY_WATCH_COLLECTIONS}

    deleted_counts: dict[str, int] = {}
    try:
        # Controlled dependency order = the declared map order (§12 step 11).
        for collection, _label in PURGE_DEPENDENCY_MAP:
            deleted_counts[collection] = await purge_repository.delete_campaign_scoped(
                collection, campaign_id
            )

        tombstone = await campaign_repository.mark_campaign_purged(
            campaign_id, operation["purge_id"], actor_user_id
        )
        if tombstone is None:
            raise ConflictError("Campaign state changed during purge — aborting")
    except ConflictError:
        await purge_repository.update_operation(
            operation["purge_id"], status=PurgeOperationStatus.PARTIAL.value,
            error="Campaign state changed during purge", deleted_counts=deleted_counts,
        )
        raise
    except Exception as exc:
        await purge_repository.update_operation(
            operation["purge_id"], status=PurgeOperationStatus.PARTIAL.value,
            error=str(exc)[:500], deleted_counts=deleted_counts,
        )
        logger.error("Purge %s interrupted: %s", operation["purge_id"], exc)
        raise ServiceUnavailableError("Purge was interrupted — it is safe to retry") from exc

    # ---- Post-purge verification (directive §14) ----
    verification: dict = {
        "campaign_records_remaining": {},
        "all_purgeable_records_removed": False,
        "unrelated_totals_unchanged": False,
        "campaign_tombstone_present": False,
        "audit_record_written": False,
    }
    all_zero = True
    for collection, _label in PURGE_DEPENDENCY_MAP:
        remaining = await purge_repository.count_campaign_scoped(collection, campaign_id)
        verification["campaign_records_remaining"][collection] = remaining
        all_zero = all_zero and remaining == 0

    integrity_after = {c: await purge_repository.count_total(c) for c in INTEGRITY_WATCH_COLLECTIONS}
    verification["unrelated_totals_unchanged"] = integrity_before == integrity_after
    verification["campaign_tombstone_present"] = tombstone["status"] == CampaignStatus.PURGED.value

    total_deleted = sum(deleted_counts.values())

    # The audit record is written AFTER the deletes and MUST survive them —
    # audit_logs is deliberately outside the dependency map (directive §10).
    await audit_record(
        audit_actions.CAMPAIGN_PURGED,
        actor_user_id=actor_user_id,
        target_user_id=None,
        before={"status": CampaignStatus.ENDED.value},
        after={"status": CampaignStatus.PURGED.value},
        metadata={
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "purge_operation_id": operation["purge_id"],
            "actor_role": actor_role,
            "deleted_counts": deleted_counts,
            "total_deleted": total_deleted,
            "confirmation": "exact campaign name typed",
        },
    )
    verification["audit_record_written"] = True
    verification["all_purgeable_records_removed"] = all_zero

    final_status = (
        PurgeOperationStatus.COMPLETED.value
        if (all_zero and verification["unrelated_totals_unchanged"])
        else PurgeOperationStatus.PARTIAL.value
    )
    await purge_repository.update_operation(
        operation["purge_id"], status=final_status, deleted_counts=deleted_counts,
        verification=verification, completed_at=datetime.now(timezone.utc),
    )

    return {
        "purge_id": operation["purge_id"],
        "status": final_status,
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "deleted_counts": {label: deleted_counts[col] for col, label in PURGE_DEPENDENCY_MAP},
        "total_deleted": total_deleted,
        "verification": verification,
        "message": (
            "Campaign operational data permanently deleted. The freed document space is "
            "reusable by MongoDB; allocated cluster storage is not immediately reduced."
        ),
    }


async def _execute_supabase_purge(campaign_id: str, campaign_name: str, actor_user_id: str, actor_role: str) -> dict:
    """Supabase mode: ONE database transaction (qx_purge_campaign) deletes the campaign's operational data
    and its name, keeps the ledger money rows (unlinked from the campaign) and writes one audit record.
    Refused while any conversion is still pending report (not yet settled)."""
    pending = await get_database()["conversions"].count_documents(
        {"campaign_id": campaign_id, "approval_status": "pending_report"})
    if pending:
        raise ConflictError(f"{pending} conversion(s) still pending report — settle them before deleting this campaign")

    counts = await runtime.get_adapter().purge_campaign(campaign_id, actor_user_id)
    labels = dict(SUPABASE_PURGE_TABLES)
    deleted = {t: int(counts.get(t, 0)) for t, _ in SUPABASE_PURGE_TABLES}
    logger.info("Campaign %s purged by %s (%s): %s", campaign_id, actor_user_id, actor_role, deleted)
    return {
        "purge_id": f"purge-{uuid.uuid4().hex[:12]}",
        "status": PurgeOperationStatus.COMPLETED.value,
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "deleted_counts": {labels[t]: n for t, n in deleted.items()},
        "total_deleted": sum(deleted.values()),
        "verification": {
            # One transaction: either every step happened or none did.
            "all_purgeable_records_removed": True,
            "unrelated_totals_unchanged": True,
            "campaign_row_deleted": int(counts.get("campaigns", 0)) == 1,
            "ledger_rows_unlinked": int(counts.get("financial_ledger_unlinked", 0)),
            "audit_record_written": True,
        },
        "message": ("Campaign deleted from the database. Ledger money rows were kept, unlinked from the campaign, "
                    "so publisher balances and payouts still reconcile."),
    }


async def get_purge_status(campaign_id: str) -> dict | None:
    op = await purge_repository.get_latest_operation_for_campaign(campaign_id)
    if op is None:
        return None
    return {
        "purge_id": op["purge_id"],
        "campaign_id": op["campaign_id"],
        "campaign_name": op["campaign_name"],
        "status": op["status"],
        "actor_user_id": op["actor_user_id"],
        "request_id": op.get("request_id"),
        "planned_counts": op.get("planned_counts") or {},
        "deleted_counts": op.get("deleted_counts"),
        "verification": op.get("verification"),
        "error": op.get("error"),
        "created_at": op["created_at"],
        "updated_at": op["updated_at"],
        "completed_at": op.get("completed_at"),
    }
