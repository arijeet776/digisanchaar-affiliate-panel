"""Company-report reconciliation endpoints (Super Admin + scoped Manager)."""
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.core.enums import Role
from app.core.rbac import CurrentUser, require_role
from app.services import conversion_review_service as svc
from app.services import offline_report_service as offline

router = APIRouter()
_reviewer = require_role(Role.SUPER_ADMIN, Role.MANAGER)


class OutcomeBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)


@router.get("")
async def list_conversions(
    approval_status: str | None = Query(default=None, pattern="^(pending_report|confirmed|rejected)$"),
    campaign_id: str | None = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(_reviewer),
):
    return await svc.list_review(user, approval_status, campaign_id, (page - 1) * page_size, page_size)


@router.get("/grouped")
async def list_conversions_grouped(
    approval_status: str | None = Query(default=None, pattern="^(pending_report|confirmed|rejected)$"),
    campaign_id: str | None = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(_reviewer),
):
    """One row per DigiSNR click ID; each event is listed under that row (see conversion_review_service)."""
    return await svc.list_review_grouped(user, approval_status, campaign_id, (page - 1) * page_size, page_size)


@router.post("/{conversion_id}/confirm")
async def confirm(conversion_id: str, request: Request, body: OutcomeBody = OutcomeBody(),
                  user: CurrentUser = Depends(_reviewer)):
    return await svc.record_outcome(user, conversion_id, True, body.note, getattr(request.state, "request_id", None))


@router.post("/{conversion_id}/reject")
async def reject(conversion_id: str, request: Request, body: OutcomeBody = OutcomeBody(),
                 user: CurrentUser = Depends(_reviewer)):
    return await svc.record_outcome(user, conversion_id, False, body.note, getattr(request.state, "request_id", None))


# ---------- Offline events: advertiser reports that never arrive as postbacks ----------

class OfflineApproveBody(BaseModel):
    campaign_id: str = Field(max_length=32)
    event_name: str = Field(min_length=1, max_length=80)
    click_ids: list[str] = Field(min_length=1, max_length=500)


class OfflineMarkBody(BaseModel):
    campaign_id: str = Field(max_length=32)
    event_name: str = Field(min_length=1, max_length=80)
    click_id: str = Field(min_length=1, max_length=64)
    status: str = Field(pattern="^(pending|rejected)$")


@router.get("/offline/campaigns")
async def offline_campaigns(user: CurrentUser = Depends(_reviewer)):
    return await offline.offline_campaigns(user)


@router.get("/offline/clicks")
async def offline_clicks(
    campaign_id: str = Query(max_length=32), event_name: str = Query(min_length=1, max_length=80),
    search: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100),
    user: CurrentUser = Depends(_reviewer),
):
    return await offline.list_offline_clicks(user, campaign_id, event_name, search, page, page_size)


@router.post("/offline/approve")
async def offline_approve(body: OfflineApproveBody, request: Request, user: CurrentUser = Depends(_reviewer)):
    return await offline.approve_clicks(user, body.campaign_id, body.event_name, body.click_ids,
                                        getattr(request.state, "request_id", None))


@router.post("/offline/mark")
async def offline_mark(body: OfflineMarkBody, request: Request, user: CurrentUser = Depends(_reviewer)):
    return await offline.mark_click(user, body.campaign_id, body.event_name, body.click_id, body.status,
                                    getattr(request.state, "request_id", None))
