"""
Manager business profile. Never holds auth credentials — see
app/schemas/user.py for why identity and profile are split.
"""
import logging
import secrets
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.exceptions import ConflictError, ServiceUnavailableError
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

COLLECTION = "managers"
MAX_ID_GENERATION_ATTEMPTS = 10


def _generate_candidate_manager_id() -> str:
    # "AM" + 5 random digits, e.g. AM97578. Random, not sequential (spec §22)
    # — a sequential id would leak how many managers exist over time.
    return "AM" + "".join(secrets.choice("0123456789") for _ in range(5))


async def create_manager_profile(user_id: str, display_name: str, mobile: str | None = None) -> dict:
    """
    Generates a unique manager_id with retry-on-collision, relying on the
    DB's unique index as the actual correctness guarantee (a random 5-digit
    suffix collision is rare but must never be silently allowed through).
    """
    db = get_database()
    now = datetime.now(timezone.utc)

    for _ in range(MAX_ID_GENERATION_ATTEMPTS):
        manager_id = _generate_candidate_manager_id()
        doc = {
            "manager_id": manager_id,
            "user_id": user_id,
            "display_name": display_name,
            "mobile": mobile,
            "created_at": now,
            "updated_at": now,
        }
        try:
            await db[COLLECTION].insert_one(doc)
            return doc
        except DuplicateKeyError:
            continue  # manager_id collision — try another candidate
        except PyMongoError as exc:
            raise ServiceUnavailableError("Manager store unavailable") from exc

    raise ConflictError("Could not generate a unique manager id, please retry")


async def get_manager_by_user_id(user_id: str) -> dict | None:
    db = get_database()
    try:
        return await db[COLLECTION].find_one({"user_id": user_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Manager store unavailable") from exc


async def get_manager_by_manager_id(manager_id: str) -> dict | None:
    db = get_database()
    try:
        return await db[COLLECTION].find_one({"manager_id": manager_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Manager store unavailable") from exc


async def list_managers() -> list[dict]:
    db = get_database()
    try:
        return await db[COLLECTION].find({}).to_list(length=1000)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Manager store unavailable") from exc


async def get_active_manager(manager_id: str) -> dict | None:
    """Manager profile only if the Manager's user account is ACTIVE (not
    pending/rejected/suspended/deactivated). Used to validate any manager
    relationship before it is trusted (Part 16.2.1)."""
    from bson import ObjectId
    from bson.errors import InvalidId

    profile = await get_manager_by_manager_id(manager_id)
    if profile is None:
        return None
    db = get_database()
    try:
        user = await db["users"].find_one({"_id": ObjectId(profile["user_id"])})
    except (InvalidId, PyMongoError):
        return None
    if user is None or user.get("account_status") != "active":
        return None
    return {**profile, "email": user["email"]}


async def list_active_managers() -> list[dict]:
    """Active Managers only — source for the Super Admin 'Assign Manager' dropdown."""
    profiles = await list_managers()
    out = []
    for p in profiles:
        active = await get_active_manager(p["manager_id"])
        if active is not None:
            out.append(active)
    return out


async def set_manager_mobile(user_id: str, mobile: str) -> bool:
    db = get_database()
    try:
        r = await db[COLLECTION].update_one(
            {"user_id": user_id}, {"$set": {"mobile": mobile, "updated_at": datetime.now(timezone.utc)}}
        )
        return r.matched_count == 1
    except PyMongoError as exc:
        raise ServiceUnavailableError("Manager store unavailable") from exc
