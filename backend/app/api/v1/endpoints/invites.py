"""
Invite creation (RBAC-scoped, spec §54-55) and a public preview endpoint
for the signup page to check validity before rendering the form.
"""
from fastapi import APIRouter, Depends

from app.core.enums import Role
from app.core.rate_limit_dependency import rate_limit
from app.core.rbac import CurrentUser, require_role
from app.db import invite_repository
from app.schemas.invite import (
    CreateManagerInviteRequest,
    CreatePublisherInviteRequest,
    InvitePreview,
    InviteResponse,
)
from app.services import invite_service

router = APIRouter()

_super_admin_or_manager = require_role(Role.SUPER_ADMIN, Role.MANAGER)
_super_admin_only = require_role(Role.SUPER_ADMIN)


@router.post(
    "/manager",
    response_model=InviteResponse,
    dependencies=[Depends(rate_limit("invite_create", limit=20, window_seconds=60))],
)
async def create_manager_invite(
    body: CreateManagerInviteRequest, user: CurrentUser = Depends(_super_admin_only)
):
    raw_token, invite = await invite_service.create_manager_invite(user.role, user.user_id, body.target_email)
    return InviteResponse(
        invite_token=raw_token,
        role=Role.MANAGER,
        target_email=invite["target_email"],
        manager_id=None,
        expires_at=invite["expires_at"],
    )


@router.post(
    "/publisher",
    response_model=InviteResponse,
    dependencies=[Depends(rate_limit("invite_create", limit=20, window_seconds=60))],
)
async def create_publisher_invite(
    body: CreatePublisherInviteRequest, user: CurrentUser = Depends(_super_admin_or_manager)
):
    raw_token, invite = await invite_service.create_publisher_invite(
        user.role, user.user_id, body.target_email, body.manager_id
    )
    return InviteResponse(
        invite_token=raw_token,
        role=Role.PUBLISHER,
        target_email=invite["target_email"],
        manager_id=invite["manager_id"],
        expires_at=invite["expires_at"],
        invitation_type=invite.get("invitation_type"),
    )


@router.get("/{token}", response_model=InvitePreview)
async def preview_invite(token: str):
    from datetime import datetime, timezone

    from app.core.enums import InviteStatus

    invite = await invite_repository.preview_invite(token)
    if invite is None:
        return InvitePreview(valid=False)

    expires_at = invite["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    is_valid = invite["status"] == InviteStatus.PENDING.value and expires_at > datetime.now(timezone.utc)
    if not is_valid:
        return InvitePreview(valid=False)

    return InvitePreview(
        valid=True,
        role=Role(invite["role"]),
        target_email=invite["target_email"],
        expires_at=invite["expires_at"],
    )


@router.post("/{token}/revoke")
async def revoke_invite(token: str, user: CurrentUser = Depends(_super_admin_or_manager)):
    revoked = await invite_service.revoke_invite(user.role, user.user_id, token)
    if not revoked:
        return {"revoked": False, "message": "Invite was already used, revoked, or expired"}
    return {"revoked": True}
