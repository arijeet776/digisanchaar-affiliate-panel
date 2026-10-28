"""
Campaigns are split across two collections, matching the same
identity/profile split pattern used for users vs. managers/publishers:

    campaigns                — identity + current status + a denormalized
                                read-model summary (name/advertiser/platform)
                                for fast listing, plus a pointer to the
                                current config version number.
    campaign_config_versions — the full, append-only, immutable history of
                                every edited configuration. A version is
                                NEVER updated or deleted once written — that
                                immutability IS the "historical protection"
                                requirement at this layer (see
                                services/campaign_service.py and
                                docs/ARCHITECTURE.md Part 3 §6-7 for what
                                this does and doesn't cover yet).

No cross-collection transaction wraps "insert new version" + "update
campaign pointer" — consistent with the same documented limitation from
Part 2 (Mongo isn't running as a replica set here). If the pointer update
somehow failed after the version insert, the version row is simply orphaned
(higher version number than campaigns.current_config_version) rather than
corrupting anything; it can be recovered by retrying the update. Flagged
here rather than silently accepted.
"""
import logging
import secrets
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.enums import ApplyScope, CampaignStatus, PauseReasonType
from app.core.exceptions import ConflictError, ServiceUnavailableError
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

CAMPAIGNS_COLLECTION = "campaigns"
VERSIONS_COLLECTION = "campaign_config_versions"
MAX_ID_GENERATION_ATTEMPTS = 10


def _generate_candidate_campaign_id() -> str:
    # "CAMP" + 4 random uppercase alnum, e.g. CAMP7K29 (spec's own example format).
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "CAMP" + "".join(secrets.choice(alphabet) for _ in range(4))


def _summary_from_fields(fields: dict) -> dict:
    return {
        "name": fields["name"],
        "advertiser_name": fields.get("advertiser_name"),
        "platform": fields.get("platform"),
    }


async def create_campaign(created_by: str, fields: dict) -> tuple[dict, dict]:
    """Returns (campaign_doc, version_doc). Retries campaign_id on collision."""
    db = get_database()
    now = datetime.now(timezone.utc)

    for _ in range(MAX_ID_GENERATION_ATTEMPTS):
        campaign_id = _generate_candidate_campaign_id()
        campaign_doc = {
            "campaign_id": campaign_id,
            "status": CampaignStatus.DRAFT.value,
            "status_reason": None,
            "status_reason_type": None,
            "current_config_version": 1,
            "summary": _summary_from_fields(fields),
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        try:
            await db[CAMPAIGNS_COLLECTION].insert_one(campaign_doc)
        except DuplicateKeyError:
            continue
        except PyMongoError as exc:
            raise ServiceUnavailableError("Campaign store unavailable") from exc

        version_doc = {
            "campaign_id": campaign_id,
            "version": 1,
            "effective_from": now,
            "apply_scope": ApplyScope.FUTURE_ONLY.value,
            "created_by": created_by,
            "created_at": now,
            **fields,
        }
        try:
            await db[VERSIONS_COLLECTION].insert_one(version_doc)
        except PyMongoError as exc:
            raise ServiceUnavailableError("Campaign store unavailable") from exc

        return campaign_doc, version_doc

    raise ConflictError("Could not generate a unique campaign id, please retry")


async def get_campaign(campaign_id: str) -> dict | None:
    db = get_database()
    try:
        return await db[CAMPAIGNS_COLLECTION].find_one({"campaign_id": campaign_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Campaign store unavailable") from exc


async def get_config_version(campaign_id: str, version: int) -> dict | None:
    db = get_database()
    try:
        return await db[VERSIONS_COLLECTION].find_one({"campaign_id": campaign_id, "version": version})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Campaign store unavailable") from exc


async def get_current_config(campaign_doc: dict) -> dict | None:
    return await get_config_version(campaign_doc["campaign_id"], campaign_doc["current_config_version"])


async def list_config_versions(campaign_id: str) -> list[dict]:
    db = get_database()
    try:
        cursor = db[VERSIONS_COLLECTION].find({"campaign_id": campaign_id}).sort("version", -1)
        return await cursor.to_list(length=1000)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Campaign store unavailable") from exc


async def create_new_version(campaign_id: str, fields: dict, apply_scope: ApplyScope, created_by: str) -> dict:
    db = get_database()
    now = datetime.now(timezone.utc)

    campaign_doc = await get_campaign(campaign_id)
    if campaign_doc is None:
        raise ServiceUnavailableError("Campaign disappeared during edit")  # caller checks existence first normally

    new_version_number = campaign_doc["current_config_version"] + 1
    version_doc = {
        "campaign_id": campaign_id,
        "version": new_version_number,
        "effective_from": now,
        "apply_scope": apply_scope.value,
        "created_by": created_by,
        "created_at": now,
        **fields,
    }
    try:
        await db[VERSIONS_COLLECTION].insert_one(version_doc)
        await db[CAMPAIGNS_COLLECTION].update_one(
            {"campaign_id": campaign_id},
            {
                "$set": {
                    "current_config_version": new_version_number,
                    "summary": _summary_from_fields(fields),
                    "updated_at": now,
                }
            },
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Campaign store unavailable") from exc

    return version_doc


async def atomic_status_transition(
    campaign_id: str,
    from_statuses: list[CampaignStatus],
    to_status: CampaignStatus,
    reason: str | None = None,
    reason_type: PauseReasonType | None = None,
) -> dict | None:
    """Same atomic-transition pattern as Part 2's onboarding approvals — only one
    concurrent request can win when the campaign is genuinely in one of `from_statuses`."""
    db = get_database()
    now = datetime.now(timezone.utc)
    try:
        return await db[CAMPAIGNS_COLLECTION].find_one_and_update(
            {"campaign_id": campaign_id, "status": {"$in": [s.value for s in from_statuses]}},
            {
                "$set": {
                    "status": to_status.value,
                    "status_reason": reason,
                    "status_reason_type": reason_type.value if reason_type else None,
                    "updated_at": now,
                }
            },
            return_document=True,
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Campaign store unavailable") from exc


async def list_campaigns(
    status: CampaignStatus | None, platform: str | None, search: str | None, skip: int, limit: int
) -> tuple[list[dict], int]:
    db = get_database()
    query: dict = {}
    if status is not None:
        query["status"] = status.value
    else:
        # Purged campaigns (Part 4 foundation, directive §16) leave normal
        # operational listings; they remain explicitly queryable via
        # ?status=purged and by direct id.
        query["status"] = {"$ne": CampaignStatus.PURGED.value}
    if platform is not None:
        query["summary.platform"] = platform
    if search:
        query["$or"] = [
            {"summary.name": {"$regex": search, "$options": "i"}},
            {"campaign_id": {"$regex": search, "$options": "i"}},
        ]
    try:
        total = await db[CAMPAIGNS_COLLECTION].count_documents(query)
        cursor = db[CAMPAIGNS_COLLECTION].find(query).sort("created_at", -1).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        return items, total
    except PyMongoError as exc:
        raise ServiceUnavailableError("Campaign store unavailable") from exc


async def count_campaigns_by_status(status: CampaignStatus) -> int:
    db = get_database()
    try:
        return await db[CAMPAIGNS_COLLECTION].count_documents({"status": status.value})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Campaign store unavailable") from exc


async def mark_campaign_purged(campaign_id: str, purge_operation_id: str, purged_by: str) -> dict | None:
    """Tombstone (directive §17): keeps ONLY the campaign identity plus purge
    metadata — campaign_id, summary name, status=PURGED, purged_at, purged_by,
    purge_operation_id. The atomic ENDED->PURGED filter means a concurrent or
    repeated purge cannot double-tombstone; callers treat None as
    already-processed. Operational payloads live in the purge dependency map
    (services/purge_service.py), never here."""
    db = get_database()
    now = datetime.now(timezone.utc)
    try:
        return await db[CAMPAIGNS_COLLECTION].find_one_and_update(
            {"campaign_id": campaign_id, "status": CampaignStatus.ENDED.value},
            {
                "$set": {
                    "status": CampaignStatus.PURGED.value,
                    "status_reason": "Operational data permanently purged",
                    "purged_at": now,
                    "purged_by": purged_by,
                    "purge_operation_id": purge_operation_id,
                    "updated_at": now,
                }
            },
            return_document=True,
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Campaign store unavailable") from exc


async def count_all_campaigns() -> int:
    db = get_database()
    try:
        return await db[CAMPAIGNS_COLLECTION].count_documents({})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Campaign store unavailable") from exc
