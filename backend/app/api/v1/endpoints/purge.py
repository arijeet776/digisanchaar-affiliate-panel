"""
Campaign data purge endpoints — Super Admin only (directive §5/§12/§28).

Mounted under /admin/campaigns alongside the Part 3 campaign router; the
paths ({id}/purge-preview, {id}/purge, {id}/purge-status) do not collide
with any Part 3 route.
"""
from fastapi import APIRouter, Depends

from app.core.enums import Role
from app.core.exceptions import NotFoundError
from app.core.rbac import CurrentUser, require_role
from app.schemas.purge import (
    PurgeOperationResponse,
    PurgePreviewResponse,
    PurgeRequest,
    PurgeResultResponse,
)
from app.services import purge_service

router = APIRouter()

_super_admin_only = require_role(Role.SUPER_ADMIN)


@router.get("/{campaign_id}/purge-preview", response_model=PurgePreviewResponse)
async def purge_preview(campaign_id: str, user: CurrentUser = Depends(_super_admin_only)):
    return await purge_service.get_purge_preview(campaign_id)


@router.post("/{campaign_id}/purge", response_model=PurgeResultResponse)
async def purge_campaign(
    campaign_id: str, body: PurgeRequest, user: CurrentUser = Depends(_super_admin_only)
):
    return await purge_service.execute_purge(
        campaign_id, body.confirm_campaign_name, user.user_id, user.role.value
    )


@router.get("/{campaign_id}/purge-status", response_model=PurgeOperationResponse)
async def purge_status(campaign_id: str, user: CurrentUser = Depends(_super_admin_only)):
    operation = await purge_service.get_purge_status(campaign_id)
    if operation is None:
        raise NotFoundError("No purge operation found for this campaign")
    return operation
