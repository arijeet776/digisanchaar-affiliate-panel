"""Click report endpoint — every role, scoped server-side (see click_report_service)."""
from fastapi import APIRouter, Depends, Query

from app.core.enums import Role
from app.core.rbac import CurrentUser, require_role
from app.services import click_report_service

router = APIRouter()
_any_role = require_role(Role.SUPER_ADMIN, Role.MANAGER, Role.PUBLISHER)


@router.get("")
async def click_report(
    campaign_id: str | None = Query(default=None, max_length=32),
    publisher_id: str | None = Query(default=None, max_length=32),
    date_from: str | None = Query(default=None, max_length=10),
    date_to: str | None = Query(default=None, max_length=10),
    search: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(_any_role),
):
    return await click_report_service.list_clicks(
        user, campaign_id=campaign_id, publisher_id=publisher_id, date_from=date_from,
        date_to=date_to, search=search, page=page, page_size=page_size)
