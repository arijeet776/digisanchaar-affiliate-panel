"""
Manager Panel endpoints (Part 4, spec §49) — MANAGER role only.

Publisher management itself (list / approve / reject / invite) stays on the
existing Part 2 endpoints (/publishers, /invites/publisher), which already
enforce manager scope — this router deliberately does NOT duplicate them.
It adds only what Part 2 didn't have: manager identity, a scoped dashboard,
and the read-only view of active network campaigns.
"""
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.enums import Role
from app.core.rbac import CurrentUser, require_role
from app.schemas.manager_panel import (
    ManagerCampaignDetail,
    ManagerCampaignListItem,
    ManagerDashboardResponse,
    ManagerMeResponse,
)
from app.core import audit_actions
from app.db import manager_repository
from app.db.audit_repository import record as audit_record
from app.services import manager_service

router = APIRouter()

_manager_only = require_role(Role.MANAGER)


@router.get("/me", response_model=ManagerMeResponse)
async def manager_me(user: CurrentUser = Depends(_manager_only)):
    return await manager_service.get_me(user.user_id)


@router.get("/dashboard", response_model=ManagerDashboardResponse)
async def manager_dashboard(user: CurrentUser = Depends(_manager_only)):
    return await manager_service.get_dashboard(user.user_id)


@router.get("/campaigns", response_model=list[ManagerCampaignListItem])
async def manager_campaigns(user: CurrentUser = Depends(_manager_only)):
    return await manager_service.list_available_campaigns()


@router.get("/campaigns/{campaign_id}", response_model=ManagerCampaignDetail)
async def manager_campaign_detail(campaign_id: str, user: CurrentUser = Depends(_manager_only)):
    return await manager_service.get_available_campaign(campaign_id)


class ManagerMobileRequest(BaseModel):
    mobile: str = Field(min_length=7, max_length=20, pattern=r"^[0-9+\-\s]+$")


@router.put("/me/mobile", response_model=ManagerMeResponse)
async def update_my_mobile(body: ManagerMobileRequest, user: CurrentUser = Depends(_manager_only)):
    """A Manager maintains their own contact number (shown to assigned Publishers)."""
    await manager_repository.set_manager_mobile(user.user_id, body.mobile.strip())
    await audit_record(audit_actions.MANAGER_MOBILE_UPDATED, actor_user_id=user.user_id, target_user_id=user.user_id)
    return await manager_service.get_me(user.user_id)
