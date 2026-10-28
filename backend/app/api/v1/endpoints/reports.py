"""Reporting endpoints (Part 8). Scope is enforced server-side: managers are
pinned to their own manager_id, publishers to their own publisher_id, and the
publisher projection drops revenue/margin entirely (spec §38/§52)."""
from fastapi import APIRouter, Depends, Query, Response

from app.core.enums import Role
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.rbac import CurrentUser, require_role
from app.db import manager_repository, publisher_repository
from app.services import reports_service

router = APIRouter()

_super_admin_only = require_role(Role.SUPER_ADMIN)
_manager_only = require_role(Role.MANAGER)
_publisher_only = require_role(Role.PUBLISHER)

_REPORT_KWARGS = (
    "date_from", "date_to", "campaign_id", "manager_id", "publisher_id",
    "event", "platform", "status", "group_by",
)


@router.get("/summary")
async def admin_report(
    user: CurrentUser = Depends(_super_admin_only),
    date_from: str | None = None,
    date_to: str | None = None,
    campaign_id: str | None = None,
    manager_id: str | None = None,
    publisher_id: str | None = None,
    event: str | None = None,
    platform: str | None = None,
    status: str | None = None,
    group_by: str = Query(default="campaign", pattern="^(campaign|manager|publisher|event)$"),
):
    return await reports_service.build_report(
        date_from=date_from, date_to=date_to, campaign_id=campaign_id,
        manager_id=manager_id, publisher_id=publisher_id, event=event,
        platform=platform, status=status, group_by=group_by,
    )


@router.get("/export.csv")
async def admin_report_csv(
    user: CurrentUser = Depends(_super_admin_only),
    date_from: str | None = None,
    date_to: str | None = None,
    campaign_id: str | None = None,
    manager_id: str | None = None,
    publisher_id: str | None = None,
    event: str | None = None,
    platform: str | None = None,
    status: str | None = None,
    group_by: str = Query(default="campaign", pattern="^(campaign|manager|publisher|event)$"),
):
    report = await reports_service.build_report(
        date_from=date_from, date_to=date_to, campaign_id=campaign_id,
        manager_id=manager_id, publisher_id=publisher_id, event=event,
        platform=platform, status=status, group_by=group_by,
    )
    return Response(
        reports_service.report_to_csv(report),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=digisanchaar-report.csv"},
    )


@router.get("/manager/summary")
async def manager_report(
    user: CurrentUser = Depends(_manager_only),
    date_from: str | None = None,
    date_to: str | None = None,
    campaign_id: str | None = None,
    publisher_id: str | None = None,
    event: str | None = None,
    group_by: str = Query(default="publisher", pattern="^(campaign|publisher|event)$"),
):
    profile = await manager_repository.get_manager_by_user_id(user.user_id)
    if profile is None:
        raise ForbiddenError("Manager profile not found for current user")
    return await reports_service.build_report(
        date_from=date_from, date_to=date_to, campaign_id=campaign_id,
        manager_id=profile["manager_id"],  # server-pinned scope — never the client's
        publisher_id=publisher_id, event=event, group_by=group_by,
    )


@router.get("/publisher/summary")
async def publisher_report(
    user: CurrentUser = Depends(_publisher_only),
    date_from: str | None = None,
    date_to: str | None = None,
    campaign_id: str | None = None,
    event: str | None = None,
    group_by: str = Query(default="campaign", pattern="^(campaign|event)$"),
):
    profile = await publisher_repository.get_publisher_by_user_id(user.user_id)
    if profile is None:
        raise NotFoundError("Publisher profile not found for current user")
    report = await reports_service.build_report(
        date_from=date_from, date_to=date_to, campaign_id=campaign_id,
        publisher_id=profile["publisher_id"],  # server-pinned
        event=event, group_by=group_by,
    )
    # Publisher projection: no revenue, no margin — ever (spec §52).
    report["totals"].pop("revenue", None)
    report["totals"].pop("margin", None)
    for row in report["rows"]:
        row.pop("revenue", None)
        row.pop("margin", None)
    return report


@router.get("/publisher/export.csv")
async def publisher_report_csv(
    user: CurrentUser = Depends(_publisher_only),
    date_from: str | None = None,
    date_to: str | None = None,
    campaign_id: str | None = None,
    event: str | None = None,
    group_by: str = Query(default="campaign", pattern="^(campaign|event)$"),
):
    profile = await publisher_repository.get_publisher_by_user_id(user.user_id)
    if profile is None:
        raise NotFoundError("Publisher profile not found for current user")
    report = await reports_service.build_report(
        date_from=date_from, date_to=date_to, campaign_id=campaign_id,
        publisher_id=profile["publisher_id"], event=event, group_by=group_by,
    )
    report["totals"].pop("revenue", None)
    report["totals"].pop("margin", None)
    for row in report["rows"]:
        row.pop("revenue", None)
        row.pop("margin", None)
    return Response(
        reports_service.report_to_csv(report),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=digisanchaar-report.csv"},
    )
