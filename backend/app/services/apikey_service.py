"""
API key management (Part 10, spec §55). Raw keys are shown exactly once at
creation; only the SHA-256 hash + display prefix are stored. Keys authenticate
the machine API via the X-API-Key header and carry explicit scopes — a key can
never do more than its scope, and revocation is immediate (DB-checked).
"""
import hashlib
import logging
import secrets
import string
from datetime import datetime, timezone

from pymongo.errors import PyMongoError

from app.core import audit_actions
from app.core.exceptions import NotFoundError, ServiceUnavailableError, UnauthorizedError
from app.db.audit_repository import record as audit_record
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

COLLECTION = "api_keys"
_VALID_SCOPES = {"reports:read", "campaigns:read"}
_ALPHABET = string.ascii_letters + string.digits


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def create_api_key(name: str, scope: str, actor_user_id: str) -> dict:
    if scope not in _VALID_SCOPES:
        from app.core.exceptions import ValidationAppError

        raise ValidationAppError(f"Unsupported scope. Allowed: {', '.join(sorted(_VALID_SCOPES))}")
    raw_key = "DGK_" + "".join(secrets.choice(_ALPHABET) for _ in range(32))
    doc = {
        "key_id": "KEY" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6)),
        "name": name,
        "key_hash": _hash(raw_key),
        "prefix": raw_key[:10],
        "scope": scope,
        "created_by": actor_user_id,
        "created_at": datetime.now(timezone.utc),
        "last_used_at": None,
        "revoked_at": None,
    }
    db = get_database()
    try:
        await db[COLLECTION].insert_one(doc)
    except PyMongoError as exc:
        raise ServiceUnavailableError("API key store unavailable") from exc
    await audit_record(
        audit_actions.API_KEY_CREATED, actor_user_id=actor_user_id,
        metadata={"key_id": doc["key_id"], "scope": scope, "name": name},
    )
    return {"key_id": doc["key_id"], "api_key": raw_key, "name": name, "scope": scope, "created_at": doc["created_at"]}


async def list_api_keys() -> list[dict]:
    db = get_database()
    try:
        docs = await db[COLLECTION].find({}).sort("created_at", -1).to_list(length=200)
    except PyMongoError as exc:
        raise ServiceUnavailableError("API key store unavailable") from exc
    return [
        {
            "key_id": d["key_id"], "name": d["name"], "prefix": d["prefix"], "scope": d["scope"],
            "created_at": d["created_at"], "last_used_at": d.get("last_used_at"),
            "revoked": d.get("revoked_at") is not None,
        }
        for d in docs
    ]


async def revoke_api_key(key_id: str, actor_user_id: str) -> dict:
    db = get_database()
    try:
        await db[COLLECTION].update_one(
            {"key_id": key_id}, {"$set": {"revoked_at": datetime.now(timezone.utc), "revoked_by": actor_user_id}}
        )
        doc = await db[COLLECTION].find_one({"key_id": key_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("API key store unavailable") from exc
    if doc is None:
        raise NotFoundError("API key not found")
    await audit_record(audit_actions.API_KEY_REVOKED, actor_user_id=actor_user_id, metadata={"key_id": key_id})
    return doc


async def verify_api_key(raw_key: str, required_scope: str) -> dict:
    """Constant-shape lookup by hash; scope and revocation checked fresh from
    the DB on every call — revocation takes effect immediately."""
    db = get_database()
    try:
        doc = await db[COLLECTION].find_one({"key_hash": _hash(raw_key)})
    except PyMongoError as exc:
        raise ServiceUnavailableError("API key store unavailable") from exc
    if doc is None or doc.get("revoked_at") is not None:
        raise UnauthorizedError("Invalid or revoked API key")
    if doc["scope"] != required_scope:
        raise UnauthorizedError("API key scope does not allow this resource")
    try:
        await db[COLLECTION].update_one(
            {"key_id": doc["key_id"]}, {"$set": {"last_used_at": datetime.now(timezone.utc)}}
        )
    except PyMongoError:
        pass
    return doc
