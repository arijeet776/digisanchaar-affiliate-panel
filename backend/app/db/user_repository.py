"""
The only place that reads the `users` collection for identity/authorization
purposes. app/core/rbac.py calls this on every authenticated request — the
JWT only proves "this is user X", never "user X currently has role Y and is
active"; that comes from here, fresh, every time.
"""
import logging

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from app.core.exceptions import ServiceUnavailableError
from app.core.enums import AccountStatus, Role
from app.db.mongodb import get_database
from app.schemas.user import UserInDB

logger = logging.getLogger(__name__)


def _doc_to_user(doc: dict) -> UserInDB:
    return UserInDB(
        id=str(doc["_id"]),
        email=doc["email"],
        password_hash=doc["password_hash"],
        role=Role(doc["role"]),
        account_status=AccountStatus(doc["account_status"]),
        email_verified=doc.get("email_verified", False),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


async def get_user_by_id(user_id: str) -> UserInDB | None:
    """
    Returns the current DB record for a user, or None if the id is malformed
    or no such user exists. Raises ServiceUnavailableError (503) if Mongo is
    unreachable — that is a dependency outage, not "user doesn't exist", and
    the two must not be confused (an outage should never look like a 401).
    """
    try:
        object_id = ObjectId(user_id)
    except (InvalidId, TypeError):
        return None

    db = get_database()
    try:
        doc = await db["users"].find_one({"_id": object_id})
    except PyMongoError as exc:
        logger.error("Mongo error while loading user %s: %s", user_id, exc)
        raise ServiceUnavailableError("User store is temporarily unavailable") from exc

    if doc is None:
        return None
    return _doc_to_user(doc)


async def get_user_by_email(email: str) -> UserInDB | None:
    db = get_database()
    try:
        doc = await db["users"].find_one({"email": email})
    except PyMongoError as exc:
        logger.error("Mongo error while loading user by email: %s", exc)
        raise ServiceUnavailableError("User store is temporarily unavailable") from exc

    if doc is None:
        return None
    return _doc_to_user(doc)
