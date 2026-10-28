"""
Refresh sessions. We never store the raw refresh token — only its `jti`
(a random session id already embedded in the token, see core/security.py).
Revoking a session means the JWT itself becomes worthless even though it
remains cryptographically valid and unexpired, because refresh always
checks this collection.
"""
import logging
from datetime import datetime, timedelta, timezone

from pymongo.errors import PyMongoError

from app.config import get_settings
from app.core.exceptions import ServiceUnavailableError
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

COLLECTION = "refresh_sessions"


async def create_session(user_id: str, jti: str) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    db = get_database()
    try:
        await db[COLLECTION].insert_one(
            {
                "jti": jti,
                "user_id": user_id,
                "created_at": now,
                "expires_at": now + timedelta(days=settings.refresh_token_expire_days),
                "revoked_at": None,
            }
        )
    except PyMongoError as exc:
        logger.error("Failed to create refresh session: %s", exc)
        raise ServiceUnavailableError("Could not start session") from exc


async def get_session(jti: str) -> dict | None:
    db = get_database()
    try:
        return await db[COLLECTION].find_one({"jti": jti})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Session store unavailable") from exc


async def revoke_session(jti: str) -> bool:
    """Returns True if a live (not-already-revoked) session was revoked."""
    db = get_database()
    try:
        result = await db[COLLECTION].update_one(
            {"jti": jti, "revoked_at": None},
            {"$set": {"revoked_at": datetime.now(timezone.utc)}},
        )
        return result.modified_count == 1
    except PyMongoError as exc:
        raise ServiceUnavailableError("Session store unavailable") from exc


async def revoke_all_sessions_for_user(user_id: str) -> int:
    """Used on deactivation/suspension/password reset (spec §16/§43)."""
    db = get_database()
    try:
        result = await db[COLLECTION].update_many(
            {"user_id": user_id, "revoked_at": None},
            {"$set": {"revoked_at": datetime.now(timezone.utc)}},
        )
        return result.modified_count
    except PyMongoError as exc:
        raise ServiceUnavailableError("Session store unavailable") from exc


async def list_sessions_for_user(user_id: str) -> list[dict]:
    """Part 11 — admin session visibility (spec: operational/security controls).

    Returns every session record (live and revoked) newest-first so an
    admin can see both what's currently active and recent history, without
    ever exposing the refresh token itself (only `jti` is ever stored —
    see module docstring).
    """
    db = get_database()
    try:
        cursor = db[COLLECTION].find({"user_id": user_id}).sort("created_at", -1).limit(100)
        return await cursor.to_list(length=100)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Session store unavailable") from exc


def is_session_live(session: dict | None) -> bool:
    if session is None or session.get("revoked_at") is not None:
        return False
    expires_at = session["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > datetime.now(timezone.utc)
