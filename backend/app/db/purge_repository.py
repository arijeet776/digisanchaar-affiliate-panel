"""
purge_operations collection — one document per campaign purge run:
{purge_id, campaign_id, campaign_name, status, actor_user_id, request_id,
planned_counts, deleted_counts, verification, error, timestamps}.

This record is what makes an interrupted purge safely retryable (directive
§13): it exists BEFORE any deletion happens, so a later call can find a
pending/running/partial operation and resume it. The deletes themselves are
idempotent by construction — every one is filtered on exactly
{"campaign_id": <id>}, so re-running them never deletes anything twice.
"""
import logging
import secrets
import string
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.enums import PurgeOperationStatus
from app.core.exceptions import ConflictError, ServiceUnavailableError
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

COLLECTION = "purge_operations"
_MAX_ID_ATTEMPTS = 5


def generate_purge_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "PURGE-" + "".join(secrets.choice(alphabet) for _ in range(8))


async def create_operation(
    campaign_id: str,
    campaign_name: str,
    actor_user_id: str,
    request_id: str | None,
    planned_counts: dict[str, int],
) -> dict:
    db = get_database()
    now = datetime.now(timezone.utc)
    for _ in range(_MAX_ID_ATTEMPTS):
        doc = {
            "purge_id": generate_purge_id(),
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "status": PurgeOperationStatus.PENDING.value,
            "actor_user_id": actor_user_id,
            "request_id": request_id,
            "planned_counts": planned_counts,
            "deleted_counts": None,
            "verification": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        }
        try:
            await db[COLLECTION].insert_one(doc)
            return doc
        except DuplicateKeyError:
            continue
        except PyMongoError as exc:
            raise ServiceUnavailableError("Purge store unavailable") from exc
    raise ConflictError("Could not allocate a purge operation id, please retry")


async def get_operation(purge_id: str) -> dict | None:
    db = get_database()
    try:
        return await db[COLLECTION].find_one({"purge_id": purge_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Purge store unavailable") from exc


async def get_latest_operation_for_campaign(campaign_id: str) -> dict | None:
    db = get_database()
    try:
        cursor = db[COLLECTION].find({"campaign_id": campaign_id}).sort("created_at", -1).limit(1)
        items = await cursor.to_list(length=1)
        return items[0] if items else None
    except PyMongoError as exc:
        raise ServiceUnavailableError("Purge store unavailable") from exc


async def get_resumable_operation(campaign_id: str) -> dict | None:
    """A pending/running/partial operation means a previous purge attempt was
    interrupted before completion — the caller resumes it instead of starting
    a second one (directive §13/§22 test 16)."""
    db = get_database()
    try:
        return await db[COLLECTION].find_one(
            {
                "campaign_id": campaign_id,
                "status": {
                    "$in": [
                        PurgeOperationStatus.PENDING.value,
                        PurgeOperationStatus.RUNNING.value,
                        PurgeOperationStatus.PARTIAL.value,
                    ]
                },
            }
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Purge store unavailable") from exc


async def update_operation(purge_id: str, **fields) -> None:
    db = get_database()
    fields["updated_at"] = datetime.now(timezone.utc)
    try:
        await db[COLLECTION].update_one({"purge_id": purge_id}, {"$set": fields})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Purge store unavailable") from exc


async def count_campaign_scoped(collection_name: str, campaign_id: str) -> int:
    if not campaign_id:
        raise ValueError("campaign_id is required for scoped counts")
    db = get_database()
    try:
        return await db[collection_name].count_documents({"campaign_id": campaign_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Purge store unavailable") from exc


async def delete_campaign_scoped(collection_name: str, campaign_id: str) -> int:
    """
    THE ONLY delete path of the purge engine (directive §7/§22 test 19-20).
    The filter is always exactly {"campaign_id": <selected campaign>} — never
    an empty filter, never a name match, never a caller-supplied filter.
    """
    if not campaign_id:
        raise ValueError("campaign_id is required for scoped deletes")
    db = get_database()
    try:
        result = await db[collection_name].delete_many({"campaign_id": campaign_id})
        return result.deleted_count
    except PyMongoError as exc:
        raise ServiceUnavailableError("Purge store unavailable") from exc


async def count_total(collection_name: str) -> int:
    """Whole-collection totals, used ONLY for before/after integrity snapshots
    (proving unrelated data is unchanged) — never for deletion."""
    db = get_database()
    try:
        return await db[collection_name].count_documents({})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Purge store unavailable") from exc
