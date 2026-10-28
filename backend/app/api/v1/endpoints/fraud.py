"""
Fraud & Security foundation (Part 3). Blocked-IP registry is fully
functional. Actual traffic enforcement (checking a blocked IP before a
click/redirect) is Part 5 — this module only manages the registry and its
admin review workflow.
"""
from fastapi import APIRouter, Depends, Query, Response

from app.core.enums import FraudBlockStatus, Role
from app.core.rbac import CurrentUser, require_role
from app.schemas.fraud import BlockedIpCreateRequest
from app.services import fraud_service

router = APIRouter()

_super_admin_only = require_role(Role.SUPER_ADMIN)


@router.get("/overview")
async def fraud_overview(user: CurrentUser = Depends(_super_admin_only)):
    return await fraud_service.get_overview()


@router.get("/blocked-ips")
async def list_blocked_ips(
    response: Response,
    status: FraudBlockStatus | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(_super_admin_only),
):
    skip = (page - 1) * page_size
    items, total = await fraud_service.list_blocked_ips(status, search, skip, page_size)
    response.headers["X-Total-Count"] = str(total)
    return items


@router.post("/blocked-ips")
async def create_blocked_ip(body: BlockedIpCreateRequest, user: CurrentUser = Depends(_super_admin_only)):
    return await fraud_service.register_blocked_ip(user.user_id, body)


@router.get("/blocked-ips/{record_id}")
async def get_blocked_ip(record_id: str, user: CurrentUser = Depends(_super_admin_only)):
    return await fraud_service.get_blocked_ip(record_id)


@router.post("/blocked-ips/{record_id}/mark-safe")
async def mark_safe(record_id: str, user: CurrentUser = Depends(_super_admin_only)):
    return await fraud_service.mark_safe(record_id, user.user_id)


@router.post("/blocked-ips/{record_id}/keep-blocked")
async def keep_blocked(record_id: str, user: CurrentUser = Depends(_super_admin_only)):
    return await fraud_service.keep_blocked(record_id, user.user_id)


@router.post("/blocked-ips/{record_id}/permanent-block")
async def permanent_block(record_id: str, user: CurrentUser = Depends(_super_admin_only)):
    return await fraud_service.permanent_block(record_id, user.user_id)


@router.post("/blocked-ips/{record_id}/investigate")
async def start_investigation(record_id: str, user: CurrentUser = Depends(_super_admin_only)):
    return await fraud_service.set_investigation(record_id, True, user.user_id)


@router.post("/blocked-ips/{record_id}/close-investigation")
async def close_investigation(record_id: str, user: CurrentUser = Depends(_super_admin_only)):
    return await fraud_service.set_investigation(record_id, False, user.user_id)
