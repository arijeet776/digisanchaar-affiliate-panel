"""
System Settings endpoints — Super Admin only (spec §28: only
SUPER_ADMIN_OWNER / authorized SUPER_ADMIN may change the tracking domain;
Manager and Publisher must be rejected).
"""
from fastapi import APIRouter, Depends

from app.core.enums import Role
from app.core.rate_limit_dependency import rate_limit
from app.core.rbac import CurrentUser, require_role
from app.schemas.settings import (
    AccentThemeResponse,
    AccentThemeUpdateRequest,
    TrackingDomainConfigResponse,
    TrackingDomainUpdateRequest,
    WhatsAppGroupResponse,
    WhatsAppGroupUpdateRequest,
)
from app.services import settings_service

router = APIRouter()
# Read-only, unauthenticated: the accent name is non-sensitive presentation
# config that every role (and the login page) needs to render the same brand.
public_router = APIRouter()

_super_admin_only = require_role(Role.SUPER_ADMIN)


@router.get("/tracking-domain", response_model=TrackingDomainConfigResponse)
async def get_tracking_domain(user: CurrentUser = Depends(_super_admin_only)):
    return await settings_service.get_tracking_domain_config()


@router.put("/tracking-domain", response_model=TrackingDomainConfigResponse)
async def update_tracking_domain(
    body: TrackingDomainUpdateRequest, user: CurrentUser = Depends(_super_admin_only)
):
    return await settings_service.update_tracking_domain(
        body.tracking_base_url, user.user_id, body.reason
    )


@router.put("/appearance", response_model=AccentThemeResponse)
async def update_accent_theme(
    body: AccentThemeUpdateRequest, user: CurrentUser = Depends(_super_admin_only)
):
    return await settings_service.update_accent_theme(body.accent_theme, user.user_id)


@router.get("/support", response_model=WhatsAppGroupResponse)
async def get_support_settings(user: CurrentUser = Depends(_super_admin_only)):
    return await settings_service.get_whatsapp_group_link()


@router.put("/support", response_model=WhatsAppGroupResponse)
async def update_support_settings(
    body: WhatsAppGroupUpdateRequest, user: CurrentUser = Depends(_super_admin_only)
):
    return await settings_service.update_whatsapp_group_link(body.whatsapp_group_link, user.user_id)


@public_router.get(
    "", response_model=AccentThemeResponse, dependencies=[Depends(rate_limit("appearance_read", limit=120, window_seconds=60))]
)
async def get_accent_theme():
    return await settings_service.get_accent_theme()
