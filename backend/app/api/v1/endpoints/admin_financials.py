"""
Super Admin / Manager financial endpoints. Every action takes an explicit
publisher_id or withdrawal_id and goes through financial_service's scope
checks — a Manager cannot widen their own access by calling these instead
of the publisher-facing wallet.py endpoints.
"""
from fastapi import APIRouter, Depends, Query

from app.api.v1.endpoints.wallet import _serialize_ledger, _serialize_withdrawal
from app.core.enums import Role
from app.core.rbac import CurrentUser, require_role
from app.schemas.financial import AdjustmentBody, MarkPaidBody, RejectWithdrawalBody, ReverseEarningBody
from app.services import financial_service

router = APIRouter()

_admin_or_manager = require_role(Role.SUPER_ADMIN, Role.MANAGER)
_admin_only = require_role(Role.SUPER_ADMIN)


@router.get("/overview")
async def financial_overview(user: CurrentUser = Depends(_admin_or_manager)):
    if user.role == Role.SUPER_ADMIN:
        return await financial_service.network_overview(user.role)
    return await financial_service.manager_overview(user.role, user.user_id)


@router.get("/wallets/{publisher_id}")
async def get_publisher_wallet(publisher_id: str, user: CurrentUser = Depends(_admin_or_manager)):
    return await financial_service.get_wallet(user.role, user.user_id, publisher_id)


@router.get("/ledger")
async def list_ledger(
    publisher_id: str | None = None,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(_admin_or_manager),
):
    items, total = await financial_service.list_ledger(user.role, user.user_id, publisher_id, None, page, page_size)
    return {"items": _serialize_ledger(items), "total": total, "page": page, "page_size": page_size}


@router.post("/ledger/{conversion_id}/reverse")
async def reverse_earning(conversion_id: str, body: ReverseEarningBody, user: CurrentUser = Depends(_admin_only)):
    row = await financial_service.reverse_earning(conversion_id=conversion_id, reason=body.reason, actor_user_id=user.user_id)
    return _serialize_ledger([row])[0]


@router.get("/withdrawals")
async def list_withdrawals(
    publisher_id: str | None = None, status: str | None = None,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(_admin_or_manager),
):
    items, total = await financial_service.list_withdrawals(user.role, user.user_id, publisher_id, status, page, page_size)
    return {"items": [_serialize_withdrawal(w) for w in items], "total": total, "page": page, "page_size": page_size}


@router.get("/withdrawals/{withdrawal_id}")
async def get_withdrawal(withdrawal_id: str, user: CurrentUser = Depends(_admin_or_manager)):
    row = await financial_service.get_withdrawal(user.role, user.user_id, withdrawal_id)
    return _serialize_withdrawal(row)


@router.post("/withdrawals/{withdrawal_id}/approve")
async def approve_withdrawal(withdrawal_id: str, user: CurrentUser = Depends(_admin_or_manager)):
    row = await financial_service.approve_withdrawal(user.role, user.user_id, withdrawal_id)
    return _serialize_withdrawal(row)


@router.post("/withdrawals/{withdrawal_id}/reject")
async def reject_withdrawal(withdrawal_id: str, body: RejectWithdrawalBody, user: CurrentUser = Depends(_admin_or_manager)):
    row = await financial_service.reject_withdrawal(user.role, user.user_id, withdrawal_id, body.reason)
    return _serialize_withdrawal(row)


@router.post("/withdrawals/{withdrawal_id}/mark-paid")
async def mark_withdrawal_paid(withdrawal_id: str, body: MarkPaidBody, user: CurrentUser = Depends(_admin_only)):
    row = await financial_service.mark_withdrawal_paid(user.role, user.user_id, withdrawal_id, body.reference)
    return _serialize_withdrawal(row)


@router.post("/adjustments")
async def create_adjustment(body: AdjustmentBody, user: CurrentUser = Depends(_admin_only)):
    row = await financial_service.create_adjustment(
        user.role, user.user_id, body.publisher_id, body.amount, body.direction, body.reason
    )
    return _serialize_ledger([row])[0]
