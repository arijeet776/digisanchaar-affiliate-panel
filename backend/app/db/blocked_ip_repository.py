"""
Blocked-IP registry (Part 3 fraud foundation). No TTL index, no automatic
expiry, by explicit requirement — a record stays BLOCKED until an
authorized admin action changes it. This is registry storage only; the
part that actually checks incoming traffic against this collection before
allowing a click/redirect is Part 5 (spec: "A blocked IP must be checked
BEFORE click creation, tracking attribution, advertiser redirect").
"""
from datetime import datetime, timezone

from bson import ObjectId
from pymongo.errors import PyMongoError

from app.core.enums import FraudBlockStatus
from app.core.exceptions import ServiceUnavailableError
from app.db.mongodb import get_database

COLLECTION = "blocked_ips"


async def find_by_ip(ip_address: str) -> dict | None:
    db = get_database()
    try:
        return await db[COLLECTION].find_one({"ip_address": ip_address})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Fraud registry unavailable") from exc


async def create_or_bump(
    ip_address: str,
    block_reason: str,
    campaign_id: str | None,
    publisher_id: str | None,
    manager_id: str | None,
    detection_source: str,
    actor_user_id: str,
) -> dict:
    """
    If this IP is already registered, bump its detection_count and
    last_detected_at rather than creating a duplicate row — the registry is
    keyed by IP, and repeat detections are exactly what it should track.
    """
    db = get_database()
    now = datetime.now(timezone.utc)
    existing = await find_by_ip(ip_address)

    if existing is not None:
        try:
            await db[COLLECTION].update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {"last_detected_at": now, "updated_by": actor_user_id, "updated_at": now},
                    "$inc": {"detection_count": 1},
                },
            )
            return await db[COLLECTION].find_one({"_id": existing["_id"]})
        except PyMongoError as exc:
            raise ServiceUnavailableError("Fraud registry unavailable") from exc

    doc = {
        "ip_address": ip_address,
        "block_reason": block_reason,
        "campaign_id": campaign_id,
        "publisher_id": publisher_id,
        "manager_id": manager_id,
        "first_detected_at": now,
        "last_detected_at": now,
        "detection_count": 1,
        "status": FraudBlockStatus.BLOCKED.value,
        "under_investigation": False,
        "detection_source": detection_source,
        "created_by": actor_user_id,
        "updated_by": actor_user_id,
        "created_at": now,
        "updated_at": now,
    }
    try:
        result = await db[COLLECTION].insert_one(doc)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Fraud registry unavailable") from exc
    doc["_id"] = result.inserted_id
    return doc


async def get_by_id(record_id: str) -> dict | None:
    db = get_database()
    try:
        return await db[COLLECTION].find_one({"_id": ObjectId(record_id)})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Fraud registry unavailable") from exc
    except Exception:  # invalid ObjectId format
        return None


async def update_status(record_id: str, status: FraudBlockStatus, actor_user_id: str) -> dict | None:
    db = get_database()
    now = datetime.now(timezone.utc)
    try:
        await db[COLLECTION].update_one(
            {"_id": ObjectId(record_id)},
            {"$set": {"status": status.value, "updated_by": actor_user_id, "updated_at": now}},
        )
        return await get_by_id(record_id)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Fraud registry unavailable") from exc


async def set_investigation_flag(record_id: str, flag: bool, actor_user_id: str) -> dict | None:
    db = get_database()
    now = datetime.now(timezone.utc)
    try:
        await db[COLLECTION].update_one(
            {"_id": ObjectId(record_id)},
            {"$set": {"under_investigation": flag, "updated_by": actor_user_id, "updated_at": now}},
        )
        return await get_by_id(record_id)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Fraud registry unavailable") from exc


async def list_blocked_ips(
    status: FraudBlockStatus | None, search: str | None, skip: int, limit: int
) -> tuple[list[dict], int]:
    db = get_database()
    query: dict = {}
    if status is not None:
        query["status"] = status.value
    if search:
        query["ip_address"] = {"$regex": search, "$options": "i"}
    try:
        total = await db[COLLECTION].count_documents(query)
        cursor = db[COLLECTION].find(query).sort("last_detected_at", -1).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        return items, total
    except PyMongoError as exc:
        raise ServiceUnavailableError("Fraud registry unavailable") from exc


async def count_by_status(status: FraudBlockStatus) -> int:
    db = get_database()
    try:
        return await db[COLLECTION].count_documents({"status": status.value})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Fraud registry unavailable") from exc


async def count_under_investigation() -> int:
    db = get_database()
    try:
        return await db[COLLECTION].count_documents({"under_investigation": True})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Fraud registry unavailable") from exc
