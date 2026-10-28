"""Publisher <-> campaign access records (approval workflow).

One record per (campaign, publisher). Only consulted for campaigns whose
approval_mode is REQUIRES_APPROVAL; PROMOTE_IMMEDIATELY campaigns still get
an APPROVED record on request so 'Approved Offers' lists them uniformly.
"""
import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.enums import CampaignApplicationStatus
from app.core.exceptions import ServiceUnavailableError
from app.db.mongodb import get_database

COLLECTION = "campaign_access"


async def get(campaign_id: str, publisher_id: str) -> dict | None:
    try:
        return await get_database()[COLLECTION].find_one(
            {"campaign_id": campaign_id, "publisher_id": publisher_id}, {"_id": 0}
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Access store unavailable") from exc


async def get_by_id(access_id: str) -> dict | None:
    try:
        return await get_database()[COLLECTION].find_one({"access_id": access_id}, {"_id": 0})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Access store unavailable") from exc


async def create(campaign_id: str, publisher_id: str, manager_id: str | None, status: CampaignApplicationStatus,
                 decided_by: str | None = None) -> tuple[dict, bool]:
    """Returns (doc, created). Unique (campaign, publisher) makes this idempotent."""
    now = datetime.now(timezone.utc)
    doc = {
        "access_id": "ACC" + uuid.uuid4().hex[:12].upper(),
        "campaign_id": campaign_id,
        "publisher_id": publisher_id,
        "manager_id": manager_id,
        "status": status.value,
        "requested_at": now,
        "decided_at": now if status != CampaignApplicationStatus.PENDING else None,
        "decided_by": decided_by,
        "note": None,
    }
    try:
        await get_database()[COLLECTION].insert_one(dict(doc))
        return doc, True
    except DuplicateKeyError:
        existing = await get(campaign_id, publisher_id)
        return existing, False
    except PyMongoError as exc:
        raise ServiceUnavailableError("Access store unavailable") from exc


async def decide(access_id: str, new_status: CampaignApplicationStatus, decided_by: str, note: str | None) -> dict | None:
    """Atomic: only a PENDING (or previously REJECTED, for re-review) record transitions."""
    try:
        return await get_database()[COLLECTION].find_one_and_update(
            {"access_id": access_id, "status": {"$in": [CampaignApplicationStatus.PENDING.value,
                                                       CampaignApplicationStatus.REJECTED.value]}},
            {"$set": {"status": new_status.value, "decided_at": datetime.now(timezone.utc),
                      "decided_by": decided_by, "note": note}},
            return_document=True, projection={"_id": 0},
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Access store unavailable") from exc


async def list_for_publisher(publisher_id: str) -> list[dict]:
    cur = get_database()[COLLECTION].find({"publisher_id": publisher_id}, {"_id": 0})
    return await cur.to_list(length=1000)


async def list_filtered(manager_id: str | None, status: str | None, skip: int, limit: int) -> tuple[list[dict], int]:
    q: dict = {}
    if manager_id:
        q["manager_id"] = manager_id
    if status:
        q["status"] = status
    col = get_database()[COLLECTION]
    total = await col.count_documents(q)
    items = await col.find(q, {"_id": 0}).sort("requested_at", -1).skip(skip).limit(limit).to_list(length=limit)
    return items, total
