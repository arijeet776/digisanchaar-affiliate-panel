"""
Invite creation, scoped by actor role (spec §17-19, §26, §54-55):
- super_admin may create MANAGER or PUBLISHER invites, and may choose the
  manager_id for a PUBLISHER invite.
- manager may create PUBLISHER invites only, always bound to their OWN
  manager_id — a manager-supplied manager_id in the request is ignored,
  never trusted (spec §25/§57).
"""
from app.core.enums import Role
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationAppError
from app.db import invite_repository, manager_repository
from app.db.audit_repository import record as audit_record
from app.core import audit_actions


async def create_manager_invite(actor_role: Role, actor_user_id: str, target_email: str | None):
    if actor_role != Role.SUPER_ADMIN:
        raise ForbiddenError("Only Super Admin can create Manager invites")

    raw_token, invite = await invite_repository.create_invite(
        role=Role.MANAGER, created_by=actor_user_id, target_email=target_email, manager_id=None
    )
    await audit_record(
        audit_actions.INVITE_CREATED,
        actor_user_id=actor_user_id,
        metadata={"role": "manager", "target_email": target_email},
    )
    return raw_token, invite


async def create_publisher_invite(
    actor_role: Role,
    actor_user_id: str,
    target_email: str | None,
    requested_manager_id: str | None,
):
    if actor_role == Role.PUBLISHER:
        raise ForbiddenError("Publishers cannot create invites")

    if actor_role == Role.MANAGER:
        manager_profile = await manager_repository.get_manager_by_user_id(actor_user_id)
        if manager_profile is None:
            raise NotFoundError("Manager profile not found for current user")
        # A manager's own invites are ALWAYS bound to themselves —
        # any manager_id in the request body is ignored, not merely validated.
        manager_id = manager_profile["manager_id"]
        if await manager_repository.get_active_manager(manager_id) is None:
            raise ForbiddenError("Your Manager account is not active")
    else:  # SUPER_ADMIN
        # Part 16.2.1: a plain Super Admin invite carries NO Manager - the
        # Manager is assigned later, at approval. (An explicit manager_id is
        # still honoured for API compatibility, but must be an ACTIVE Manager.)
        manager_id = None
        if requested_manager_id:
            if await manager_repository.get_active_manager(requested_manager_id) is None:
                raise NotFoundError(f"No active manager found with manager_id={requested_manager_id}")
            manager_id = requested_manager_id

    invitation_type = (
        invite_repository.INVITE_TYPE_MANAGER if manager_id else invite_repository.INVITE_TYPE_SUPER_ADMIN
    )
    raw_token, invite = await invite_repository.create_invite(
        role=Role.PUBLISHER, created_by=actor_user_id, target_email=target_email, manager_id=manager_id,
        invitation_type=invitation_type,
    )
    await audit_record(
        audit_actions.INVITE_CREATED,
        actor_user_id=actor_user_id,
        metadata={"role": "publisher", "target_email": target_email, "manager_id": manager_id,
                  "invitation_type": invitation_type},
    )
    return raw_token, invite


async def revoke_invite(actor_role: Role, actor_user_id: str, raw_token: str) -> bool:
    """
    Only the invite's creator or a Super Admin may revoke it (spec §19's
    "creator binding" requirement, applied to revocation as well as
    creation). A Manager cannot revoke another Manager's — or Super
    Admin's — invite.
    """
    invite = await invite_repository.get_invite_by_token(raw_token)
    if invite is None:
        raise NotFoundError("Invite not found")

    if actor_role != Role.SUPER_ADMIN and invite["created_by"] != actor_user_id:
        raise ForbiddenError("You did not create this invite")

    revoked = await invite_repository.revoke_invite(invite["_id"])
    if revoked:
        await audit_record(
            audit_actions.INVITE_REVOKED, actor_user_id=actor_user_id,
            metadata={"invite_id": str(invite["_id"])},
        )
    return revoked
