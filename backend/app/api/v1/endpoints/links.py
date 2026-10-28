"""Tracking link management (Part 5) — authenticated panel endpoints.

Generation: Super Admin (any publisher) and Manager (own publishers only).
Listing: Super Admin sees all, Manager own scope, Publisher own links.
The canonical tracking URL is built server-side from the configured tracking
domain — the frontend never constructs one (spec §29).
"""
from fastapi import APIRouter, Depends

from app.core.enums import Role
from app.core.rate_limit_dependency import rate_limit
from app.core.rbac import CurrentUser, require_role
from app.schemas.tracking import TrackingLinkCreateRequest, TrackingLinkResponse
from app.services import tracking_service

router = APIRouter()

_link_creators = require_role(Role.SUPER_ADMIN, Role.MANAGER)
_panel_roles = require_role(Role.SUPER_ADMIN, Role.MANAGER, Role.PUBLISHER)


@router.post(
    "",
    response_model=TrackingLinkResponse,
    dependencies=[Depends(rate_limit("link_create", limit=20, window_seconds=60))],
)
async def create_tracking_link(
    body: TrackingLinkCreateRequest, user: CurrentUser = Depends(_link_creators)
):
    return await tracking_service.generate_tracking_link(body.campaign_id, body.publisher_id, user)


@router.get("", response_model=list[TrackingLinkResponse])
async def list_tracking_links(user: CurrentUser = Depends(_panel_roles)):
    return await tracking_service.list_links(user)
