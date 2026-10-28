"""Campaign access: publisher self-serve + manager/admin approvals."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.enums import Role
from app.core.rbac import CurrentUser, require_role
from app.services import campaign_access_service as svc

router = APIRouter()
_publisher = require_role(Role.PUBLISHER)
_reviewer = require_role(Role.SUPER_ADMIN, Role.MANAGER)


class DecisionBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)


@router.get("/available")
async def available(
    search: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=60),
    kind: str | None = Query(default=None, pattern="^(standard|shopping|survey)$"),
    country: str | None = Query(default=None, max_length=60),
    mode: str | None = Query(default=None, pattern="^(promote_immediately|requires_approval)$"),
    sort: str = Query(default="newest", pattern="^(newest|oldest|payout)$"),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=50),
    user: CurrentUser = Depends(_publisher),
):
    return await svc.list_available(user, (page - 1) * page_size, page_size, search, category, kind, country, mode, sort)


@router.post("/{campaign_id}/access")
async def request_access(campaign_id: str, user: CurrentUser = Depends(_publisher)):
    return await svc.request_access(user, campaign_id)


@router.get("/applications")
async def applications(
    status: str | None = Query(default=None, pattern="^(pending|approved|rejected)$"),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(_reviewer),
):
    return await svc.list_applications(user, status, (page - 1) * page_size, page_size)


@router.post("/applications/{access_id}/approve")
async def approve(access_id: str, body: DecisionBody = DecisionBody(), user: CurrentUser = Depends(_reviewer)):
    return await svc.decide(user, access_id, True, body.note)


@router.post("/applications/{access_id}/reject")
async def reject(access_id: str, body: DecisionBody = DecisionBody(), user: CurrentUser = Depends(_reviewer)):
    return await svc.decide(user, access_id, False, body.note)
