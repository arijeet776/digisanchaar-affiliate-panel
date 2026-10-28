"""
Invites. The raw token is shown to the caller exactly once (at creation);
only its sha256 hash is ever stored (core.security.hash_token — deterministic,
so we can look it up by hash later, unlike bcrypt).

`claim_invite` is the key correctness primitive: it atomically flips a
PENDING invite to USED in the same operation that checks it's still valid,
so two concurrent signups racing on the same token can never both succeed
(spec §29's race-condition requirement, applied to invites as well as
approvals).
"""
import logging
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.enums import InviteStatus, Role
from app.core.exceptions import ConflictError, ServiceUnavailableError
from app.core.security import generate_secure_token, hash_token
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

COLLECTION = "invites"

# Resolved server-side from who created the invite and whether a Manager
# relationship is bound to it - never supplied by the invitee.
INVITE_TYPE_MANAGER = "MANAGER_INVITE"          # publisher invite bound to a Manager
INVITE_TYPE_SUPER_ADMIN = "SUPER_ADMIN_INVITE"  # publisher invite with no Manager yet


async def create_invite(
    role: Role,
    created_by: str,
    target_email: str | None = None,
    manager_id: str | None = None,
    ttl_hours: int = 72,
    invitation_type: str | None = None,
) -> tuple[str, dict]:
    """Returns (raw_token, invite_document). raw_token is never persisted."""
    from datetime import timedelta

    raw_token = generate_secure_token()
    now = datetime.now(timezone.utc)
    doc = {
        "token_hash": hash_token(raw_token),
        "role": role.value,
        "target_email": target_email,
        "manager_id": manager_id,  # set for Manager-bound publisher invites; null for Manager invites and Super Admin publisher invites
        "invitation_type": invitation_type,
        "created_by": created_by,
        "status": InviteStatus.PENDING.value,
        "created_at": now,
        "expires_at": now + timedelta(hours=ttl_hours),
        "used_at": None,
        "revoked_at": None,
    }
    db = get_database()
    try:
        result = await db[COLLECTION].insert_one(doc)
    except DuplicateKeyError as exc:  # astronomically unlikely token collision
        raise ConflictError("Could not generate a unique invite token, please retry") from exc
    except PyMongoError as exc:
        raise ServiceUnavailableError("Invite store unavailable") from exc

    doc["_id"] = result.inserted_id
    return raw_token, doc


async def preview_invite(raw_token: str) -> dict | None:
    """Read-only lookup for the signup page to show role/expiry before submitting the form."""
    db = get_database()
    try:
        return await db[COLLECTION].find_one({"token_hash": hash_token(raw_token)})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Invite store unavailable") from exc


async def claim_invite(raw_token: str) -> dict | None:
    """
    Atomically validates AND consumes an invite in one operation. Returns
    the invite document if the claim succeeded, or None if the token is
    unknown/already used/revoked/expired — i.e. the caller cannot
    distinguish "never existed" from "already used" from this, which is
    intentional (no information leak about invite state to a guesser).
    """
    db = get_database()
    now = datetime.now(timezone.utc)
    try:
        doc = await db[COLLECTION].find_one_and_update(
            {
                "token_hash": hash_token(raw_token),
                "status": InviteStatus.PENDING.value,
                "expires_at": {"$gt": now},
            },
            {"$set": {"status": InviteStatus.USED.value, "used_at": now}},
        )
        return doc
    except PyMongoError as exc:
        raise ServiceUnavailableError("Invite store unavailable") from exc


async def release_invite(invite_id) -> None:
    """
    Compensating action: puts a claimed invite back to PENDING if the
    signup that consumed it failed after the claim (e.g. a duplicate-email
    race lost to another request). Mongo here isn't a replica set, so we
    don't have multi-document ACID transactions across the invites and
    users collections — this compensating update is the documented
    alternative (see docs/ARCHITECTURE.md).
    """
    db = get_database()
    try:
        await db[COLLECTION].update_one(
            {"_id": invite_id, "status": InviteStatus.USED.value},
            {"$set": {"status": InviteStatus.PENDING.value, "used_at": None}},
        )
    except PyMongoError as exc:
        logger.error("Failed to release invite %s back to PENDING: %s", invite_id, exc)


async def revoke_invite(invite_id) -> bool:
    db = get_database()
    try:
        result = await db[COLLECTION].update_one(
            {"_id": invite_id, "status": InviteStatus.PENDING.value},
            {"$set": {"status": InviteStatus.REVOKED.value, "revoked_at": datetime.now(timezone.utc)}},
        )
        return result.modified_count == 1
    except PyMongoError as exc:
        raise ServiceUnavailableError("Invite store unavailable") from exc


async def get_invite_by_token(raw_token: str) -> dict | None:
    """Alias of preview_invite, named for callers that need it for authorization checks
    (e.g. confirming who created an invite before allowing revocation)."""
    return await preview_invite(raw_token)
