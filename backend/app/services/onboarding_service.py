"""
Manager/Publisher signup and approval/rejection.

Signup ordering (spec §20/§27, and the compensating-action note in
db/invite_repository.py): check email uniqueness first, THEN atomically
claim the invite, THEN insert the user. If the user insert still loses a
race on the DB's unique email index, we release the invite back to PENDING
rather than leaving it burned for nothing — Mongo here has no cross-
collection ACID transaction (not deployed as a replica set), so this is a
compensating action, not a real distributed transaction.

Approval/rejection ordering (spec §21/§28/§29, the race-condition
requirement): a single atomic `find_one_and_update` filtered on
`account_status: PENDING` is what guarantees exactly one concurrent
request can ever perform the transition — everything after that check
(business id generation, audit log, email) only runs for the request that
actually won the atomic update, which is what makes "exactly one Publisher
ID, exactly one approval email" true even under concurrent approval clicks.
"""
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core import audit_actions
from app.core.email_utils import normalize_email
from app.core.enums import AccountStatus, OTPPurpose, Role
from app.core.exceptions import (
    ConflictError, ForbiddenError, NotFoundError, UnauthorizedError, ValidationAppError,
)
from app.core.security import hash_password
from app.db import invite_repository, manager_repository, publisher_repository
from app.db.audit_repository import record as audit_record
from app.db.mongodb import get_database
from app.services import email_service, otp_service

USERS_COLLECTION = "users"


REGISTRATION_SOURCE_OPEN = "OPEN_REGISTRATION"


class AlreadyProcessedError(ConflictError):
    code = "ALREADY_PROCESSED"


async def _find_user_by_email(email: str) -> dict | None:
    db = get_database()
    return await db[USERS_COLLECTION].find_one({"email": email})


async def _insert_pending_user(email: str, password: str, role: Role) -> dict:
    db = get_database()
    now = datetime.now(timezone.utc)
    doc = {
        "email": email,
        "password_hash": hash_password(password),
        "role": role.value,
        "account_status": AccountStatus.PENDING.value,
        "email_verified": False,
        "created_at": now,
        "updated_at": now,
    }
    result = await db[USERS_COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def signup_manager(invite_token: str, email: str, password: str, display_name: str, mobile: str | None = None) -> dict:
    email = normalize_email(email)

    invite = await invite_repository.preview_invite(invite_token)
    if invite is None or invite["role"] != Role.MANAGER.value:
        raise UnauthorizedError("Invalid or expired invite")
    if invite.get("target_email") and normalize_email(invite["target_email"]) != email:
        raise UnauthorizedError("This invite was issued for a different email address")

    if await _find_user_by_email(email) is not None:
        raise ConflictError("An account with this email already exists")

    claimed = await invite_repository.claim_invite(invite_token)
    if claimed is None:
        # Lost a race to another signup using the same token, or it expired
        # in between the preview and this claim.
        raise UnauthorizedError("Invalid or expired invite")

    try:
        user = await _insert_pending_user(email, password, Role.MANAGER)
    except DuplicateKeyError:
        await invite_repository.release_invite(claimed["_id"])
        raise ConflictError("An account with this email already exists")

    user_id = str(user["_id"])
    await manager_repository.create_manager_profile(user_id=user_id, display_name=display_name, mobile=mobile)

    await audit_record(audit_actions.USER_REGISTERED, actor_user_id=user_id, target_user_id=user_id,
                        metadata={"role": "manager"})
    await audit_record(audit_actions.INVITE_USED, actor_user_id=user_id, metadata={"invite_id": str(claimed["_id"])})

    # No email OTP at signup: the account stays PENDING until a Super Admin approves it.

    return user


async def signup_publisher(invite_token: str | None, email: str, password: str, display_name: str, mobile: str | None = None, company: str | None = None) -> dict:
    """Public Publisher registration (Part 17). An invite is NOT required.

    - No invite: source OPEN_REGISTRATION, manager_id = None. The Manager (if
      any) is assigned by a Super Admin later. Mobile + Company are required.
    - With an invite (legacy Manager/Super Admin link): behaves as before; the
      Manager relationship comes only from the server-side invite record.
    Nothing in the request can set manager_id (schema is extra="forbid")."""
    email = normalize_email(email)
    invite_token = (invite_token or "").strip() or None

    claimed = None
    invite = None
    if invite_token:
        invite = await invite_repository.preview_invite(invite_token)
        if invite is None or invite["role"] != Role.PUBLISHER.value:
            raise UnauthorizedError("Invalid or expired invite")
        if invite.get("target_email") and normalize_email(invite["target_email"]) != email:
            raise UnauthorizedError("This invite was issued for a different email address")
        # A Manager that was suspended/deactivated after issuing the invite
        # cannot onboard publishers (relationship re-validated NOW).
        invite_manager_id = invite.get("manager_id")
        if invite_manager_id and await manager_repository.get_active_manager(invite_manager_id) is None:
            raise ConflictError("This invitation is no longer valid")
    else:
        if not (mobile and mobile.strip()):
            raise ValidationAppError("Mobile number is required")
        if not (company and company.strip()):
            raise ValidationAppError("Company is required")

    if await _find_user_by_email(email) is not None:
        raise ConflictError("An account with this email already exists")

    if invite_token:
        claimed = await invite_repository.claim_invite(invite_token)
        if claimed is None:
            raise UnauthorizedError("Invalid or expired invite")

    try:
        user = await _insert_pending_user(email, password, Role.PUBLISHER)
    except DuplicateKeyError:
        if claimed is not None:
            await invite_repository.release_invite(claimed["_id"])
        raise ConflictError("An account with this email already exists")

    user_id = str(user["_id"])
    if claimed is not None:
        manager_id = claimed.get("manager_id")
        invitation_type = claimed.get("invitation_type") or (
            invite_repository.INVITE_TYPE_MANAGER if manager_id else invite_repository.INVITE_TYPE_SUPER_ADMIN
        )
        invited_by, invite_id = claimed.get("created_by"), str(claimed["_id"])
    else:
        manager_id, invitation_type, invited_by, invite_id = None, REGISTRATION_SOURCE_OPEN, None, None

    publisher = await publisher_repository.create_publisher_profile(
        user_id=user_id, manager_id=manager_id, display_name=display_name,
        mobile=mobile.strip() if mobile else None, company=company.strip() if company else None,
        invitation_type=invitation_type, invited_by=invited_by, invite_id=invite_id,
    )

    await audit_record(audit_actions.USER_REGISTERED, actor_user_id=user_id, target_user_id=user_id,
                        metadata={"role": "publisher", "manager_id": manager_id, "invitation_type": invitation_type})
    await audit_record(audit_actions.PUBLISHER_APPLICATION_SUBMITTED, actor_user_id=user_id, target_user_id=user_id,
                        metadata={"publisher_id": publisher["publisher_id"], "invitation_type": invitation_type,
                                  "manager_id": manager_id})
    await _notify_application_submitted(user, publisher)
    if claimed is not None:
        await audit_record(audit_actions.INVITE_USED, actor_user_id=user_id, metadata={"invite_id": invite_id})

    # No email OTP at signup: the account stays PENDING until a Super Admin approves it.

    return user


async def _super_admin_emails() -> list[str]:
    db = get_database()
    cursor = db[USERS_COLLECTION].find({"role": Role.SUPER_ADMIN.value, "account_status": AccountStatus.ACTIVE.value})
    return [u["email"] async for u in cursor]


async def _manager_email(manager_id: str) -> str | None:
    m = await manager_repository.get_active_manager(manager_id)
    return m["email"] if m else None


async def _notify_application_submitted(user: dict, publisher: dict) -> None:
    """Super Admins always; the assigned Manager only when one is already
    resolved (never for an unassigned Super Admin invite). De-duplicated by
    address so one person holding both is emailed once."""
    recipients: list[str] = []
    needs_manager = not publisher.get("manager_id")
    if publisher.get("manager_id"):
        mgr = await _manager_email(publisher["manager_id"])
        if mgr:
            recipients.append(mgr)
    recipients += await _super_admin_emails()
    seen: set[str] = set()
    for to in recipients:
        if to in seen:
            continue
        seen.add(to)
        await email_service.send_publisher_application_received(
            to, publisher["display_name"], publisher["publisher_id"], needs_manager
        )


async def _atomic_transition(user_id, from_status: AccountStatus, to_status: AccountStatus) -> dict | None:
    """Returns the updated user document if THIS call performed the transition, else None."""
    from bson import ObjectId

    db = get_database()
    return await db[USERS_COLLECTION].find_one_and_update(
        {"_id": ObjectId(user_id), "account_status": from_status.value},
        {"$set": {"account_status": to_status.value, "updated_at": datetime.now(timezone.utc)}},
        return_document=True,
    )


async def approve_manager(target_user_id: str, actor_user_id: str) -> dict:
    updated = await _atomic_transition(target_user_id, AccountStatus.PENDING, AccountStatus.ACTIVE)
    if updated is None:
        raise AlreadyProcessedError("This manager application has already been processed")

    manager_profile = await manager_repository.get_manager_by_user_id(target_user_id)
    await audit_record(
        audit_actions.MANAGER_APPROVED, actor_user_id=actor_user_id, target_user_id=target_user_id,
        before={"account_status": "pending"}, after={"account_status": "active"},
    )
    if manager_profile:
        await email_service.send_manager_approved(updated["email"], manager_profile["manager_id"])
    return updated


async def reject_manager(target_user_id: str, actor_user_id: str, reason: str | None) -> dict:
    updated = await _atomic_transition(target_user_id, AccountStatus.PENDING, AccountStatus.REJECTED)
    if updated is None:
        raise AlreadyProcessedError("This manager application has already been processed")

    await audit_record(
        audit_actions.MANAGER_REJECTED, actor_user_id=actor_user_id, target_user_id=target_user_id,
        before={"account_status": "pending"}, after={"account_status": "rejected"}, reason=reason,
    )
    return updated


async def _require_manager_scope(actor_role: Role, actor_user_id: str, target_publisher: dict) -> None:
    if actor_role == Role.SUPER_ADMIN:
        return
    if actor_role != Role.MANAGER:
        raise ForbiddenError("Only Super Admin or the assigned Manager may act on this Publisher")
    acting_manager = await manager_repository.get_manager_by_user_id(actor_user_id)
    if acting_manager is None or acting_manager["manager_id"] != target_publisher["manager_id"]:
        raise ForbiddenError("You do not have authority over this Publisher")


async def approve_publisher(
    target_user_id: str, actor_role: Role, actor_user_id: str, assign_manager_id: str | None = None
) -> dict:
    """
    Approve a PENDING publisher.

    - Manager-linked application: the assigned Manager or a Super Admin may
      approve; the existing relationship is kept. A different manager_id in
      the request is refused (reassignment is not part of approval).
    - Unassigned application (open registration / Super Admin invite): ONLY a
      Super Admin may act. Choosing a Manager is OPTIONAL (Part 17): without
      one the publisher becomes ACTIVE with manager_id = null and shows
      "Not assigned yet". With one: assign (conditional on still-unassigned)
      -> atomic PENDING->ACTIVE -> a lost race compensates the assignment. Mongo here has no cross-collection transaction (see module
      docstring), so this is the documented compensating-action pattern.
    - Idempotent: the atomic status transition is the single winner; a second
      approval gets ALREADY_PROCESSED and no id/email/notification side effect.
    """
    publisher_profile = await publisher_repository.get_publisher_by_user_id(target_user_id)
    if publisher_profile is None:
        raise NotFoundError("Publisher not found")
    await _require_manager_scope(actor_role, actor_user_id, publisher_profile)

    current_manager_id = publisher_profile.get("manager_id")
    newly_assigned = False
    effective_manager_id = current_manager_id

    if current_manager_id:
        if assign_manager_id and assign_manager_id != current_manager_id:
            raise ValidationAppError("This publisher already has a Manager; use Reassign Manager instead")
    elif assign_manager_id:
        # Optional "Approve & Assign Manager" - Super Admin only, ACTIVE manager only.
        if actor_role != Role.SUPER_ADMIN:
            raise ForbiddenError("Only Super Admin can assign a Manager")
        if await manager_repository.get_active_manager(assign_manager_id) is None:
            raise ValidationAppError("The selected Manager is not an active Manager")
        newly_assigned = await publisher_repository.assign_manager_if_unassigned(target_user_id, assign_manager_id)
        if not newly_assigned:
            fresh = await publisher_repository.get_publisher_by_user_id(target_user_id)
            if not fresh or fresh.get("manager_id") != assign_manager_id:
                raise AlreadyProcessedError("This publisher was assigned to a different Manager")
        effective_manager_id = assign_manager_id
    elif actor_role != Role.SUPER_ADMIN:
        # Unassigned applications (open registration) are a Super Admin matter.
        raise ForbiddenError("Only Super Admin can approve an unassigned publisher")
    # else: Super Admin approving without a Manager -> ACTIVE, manager_id stays null.

    updated = await _atomic_transition(target_user_id, AccountStatus.PENDING, AccountStatus.ACTIVE)
    if updated is None:
        if newly_assigned:
            # We assigned but did not win the activation (already approved /
            # rejected in between): undo OUR assignment, nothing else.
            await publisher_repository.unassign_manager(target_user_id, assign_manager_id)
        raise AlreadyProcessedError("This publisher application has already been processed")

    await audit_record(
        audit_actions.PUBLISHER_APPROVED, actor_user_id=actor_user_id, target_user_id=target_user_id,
        before={"account_status": "pending"}, after={"account_status": "active", "manager_id": effective_manager_id},
    )
    if newly_assigned:
        await audit_record(
            audit_actions.PUBLISHER_MANAGER_ASSIGNED, actor_user_id=actor_user_id, target_user_id=target_user_id,
            before={"manager_id": None}, after={"manager_id": effective_manager_id},
        )
        mgr_email = await _manager_email(effective_manager_id)
        if mgr_email:
            await email_service.send_publisher_assigned(
                mgr_email, publisher_profile["display_name"], publisher_profile["publisher_id"]
            )
    await email_service.send_publisher_approved(updated["email"], publisher_profile["publisher_id"])
    return updated


async def reject_publisher(target_user_id: str, actor_role: Role, actor_user_id: str, reason: str | None) -> dict:
    publisher_profile = await publisher_repository.get_publisher_by_user_id(target_user_id)
    if publisher_profile is None:
        raise NotFoundError("Publisher not found")
    await _require_manager_scope(actor_role, actor_user_id, publisher_profile)

    updated = await _atomic_transition(target_user_id, AccountStatus.PENDING, AccountStatus.REJECTED)
    if updated is None:
        raise AlreadyProcessedError("This publisher application has already been processed")

    await audit_record(
        audit_actions.PUBLISHER_REJECTED, actor_user_id=actor_user_id, target_user_id=target_user_id,
        before={"account_status": "pending"}, after={"account_status": "rejected"}, reason=reason,
    )
    return updated


async def assign_manager(target_user_id: str, manager_id: str, actor_user_id: str) -> dict:
    """Super Admin: assign (or reassign) a Manager to a non-rejected publisher
    at any time. The target must be an ACTIVE manager. Historical clicks and
    conversions keep the manager they were recorded with; the new Manager
    applies to activity from now on."""
    publisher = await publisher_repository.get_publisher_by_user_id(target_user_id)
    if publisher is None:
        raise NotFoundError("Publisher not found")
    user = await get_database()[USERS_COLLECTION].find_one({"_id": _oid(target_user_id)})
    if user is None or user.get("account_status") == AccountStatus.REJECTED.value:
        raise ConflictError("A rejected publisher cannot be assigned a Manager")
    if await manager_repository.get_active_manager(manager_id) is None:
        raise ValidationAppError("The selected Manager is not an active Manager")
    previous = publisher.get("manager_id")
    if previous == manager_id:
        return publisher  # idempotent: no change, no audit, no email
    await publisher_repository.set_manager(target_user_id, manager_id)
    await audit_record(
        audit_actions.PUBLISHER_MANAGER_REASSIGNED if previous else audit_actions.PUBLISHER_MANAGER_ASSIGNED,
        actor_user_id=actor_user_id, target_user_id=target_user_id,
        before={"manager_id": previous}, after={"manager_id": manager_id},
    )
    mgr_email = await _manager_email(manager_id)
    if mgr_email:
        await email_service.send_publisher_assigned(mgr_email, publisher["display_name"], publisher["publisher_id"])
    return await publisher_repository.get_publisher_by_user_id(target_user_id)


def _oid(value: str):
    from bson import ObjectId

    return ObjectId(value)
