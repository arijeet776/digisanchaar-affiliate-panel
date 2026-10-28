"""
Publisher business profile. manager_id here comes ONLY from the invite that
was claimed to create this publisher (see onboarding_service) — never from
client-supplied signup payload fields (spec §25/§57).
"""
import logging
import secrets
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.exceptions import ConflictError, ServiceUnavailableError
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

COLLECTION = "publishers"
MAX_ID_GENERATION_ATTEMPTS = 10


def _generate_candidate_publisher_id() -> str:
    # 4-digit random-looking id (spec §6/§30) — never sequential.
    return "".join(secrets.choice("0123456789") for _ in range(4))


async def create_publisher_profile(user_id: str, manager_id: str | None, display_name: str,
                                   mobile: str | None = None, company: str | None = None,
                                   invitation_type: str | None = None, invited_by: str | None = None,
                                   invite_id: str | None = None) -> dict:
    db = get_database()
    now = datetime.now(timezone.utc)

    for _ in range(MAX_ID_GENERATION_ATTEMPTS):
        publisher_id = _generate_candidate_publisher_id()
        doc = {
            "publisher_id": publisher_id,
            "user_id": user_id,
            "manager_id": manager_id,
            "display_name": display_name,
            "mobile": mobile,
            "company": company,
            # Onboarding provenance (Part 16.2.1). manager_id is None until a
            # Super Admin assigns one at approval (SUPER_ADMIN_INVITE).
            "invitation_type": invitation_type,
            "invited_by": invited_by,
            "invite_id": invite_id,
            "created_at": now,
            "updated_at": now,
        }
        try:
            await db[COLLECTION].insert_one(doc)
            return doc
        except DuplicateKeyError:
            continue
        except PyMongoError as exc:
            raise ServiceUnavailableError("Publisher store unavailable") from exc

    raise ConflictError("Could not generate a unique publisher id, please retry")


async def get_publisher_by_user_id(user_id: str) -> dict | None:
    db = get_database()
    try:
        return await db[COLLECTION].find_one({"user_id": user_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Publisher store unavailable") from exc


async def list_publishers_by_manager(manager_id: str) -> list[dict]:
    db = get_database()
    try:
        return await db[COLLECTION].find({"manager_id": manager_id}).to_list(length=1000)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Publisher store unavailable") from exc


async def list_all_publishers() -> list[dict]:
    db = get_database()
    try:
        return await db[COLLECTION].find({}).to_list(length=1000)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Publisher store unavailable") from exc


async def get_publisher_by_publisher_id(publisher_id: str) -> dict | None:
    """Lookup by the business identifier (additive, Part 5) — tracking-link
    generation and the click pipeline resolve publishers by publisher_id."""
    db = get_database()
    try:
        return await db[COLLECTION].find_one({"publisher_id": publisher_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Publisher store unavailable") from exc


async def assign_manager_if_unassigned(user_id: str, manager_id: str) -> bool:
    """Atomically sets manager_id only while it is still unset, so two
    concurrent assignments can never overwrite each other."""
    db = get_database()
    try:
        r = await db[COLLECTION].update_one(
            {"user_id": user_id, "manager_id": None},
            {"$set": {"manager_id": manager_id, "updated_at": datetime.now(timezone.utc)}},
        )
        return r.modified_count == 1
    except PyMongoError as exc:
        raise ServiceUnavailableError("Publisher store unavailable") from exc


async def unassign_manager(user_id: str, manager_id: str) -> None:
    """Compensating action for a failed approve-and-assign (see onboarding_service)."""
    db = get_database()
    try:
        await db[COLLECTION].update_one(
            {"user_id": user_id, "manager_id": manager_id},
            {"$set": {"manager_id": None, "updated_at": datetime.now(timezone.utc)}},
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Publisher store unavailable") from exc


async def set_manager(user_id: str, manager_id: str) -> None:
    """Unconditional set (Super Admin assign/reassign; callers validate)."""
    db = get_database()
    try:
        await db[COLLECTION].update_one(
            {"user_id": user_id}, {"$set": {"manager_id": manager_id, "updated_at": datetime.now(timezone.utc)}}
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Publisher store unavailable") from exc
