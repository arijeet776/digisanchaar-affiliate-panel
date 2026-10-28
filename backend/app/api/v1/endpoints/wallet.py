"""
Publisher-facing financial endpoints — a Publisher sees only their own
wallet/earnings/ledger/withdrawals. A Manager or Super Admin uses the
admin_financials.py endpoints instead, which take an explicit publisher_id
and go through the same scope checks in financial_service.
"""
from fastapi import APIRouter, Depends, Query

from app.core.enums import Role
from app.core.logging_config import request_id_ctx
from app.core.rbac import CurrentUser, require_role
from app.schemas.financial import WithdrawalRequestBody
from app.services import financial_service

router = APIRouter()

_publisher_only = require_role(Role.PUBLISHER)


@router.get("/summary")
async def wallet_summary(user: CurrentUser = Depends(_publisher_only)):
    from app.db.publisher_repository import get_publisher_by_user_id

    profile = await get_publisher_by_user_id(user.user_id)
    if profile is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Publisher profile not found")
    return await financial_service.get_wallet(user.role, user.user_id, profile["publisher_id"])


@router.get("/earnings")
async def wallet_earnings(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(_publisher_only),
):
    from app.db.publisher_repository import get_publisher_by_user_id

    profile = await get_publisher_by_user_id(user.user_id)
    if profile is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Publisher profile not found")
    items, total = await financial_service.list_earnings(user.role, user.user_id, profile["publisher_id"], page, page_size)
    return {"items": _serialize_ledger(items), "total": total, "page": page, "page_size": page_size}


@router.get("/ledger")
async def wallet_ledger(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(_publisher_only),
):
    items, total = await financial_service.list_ledger(user.role, user.user_id, None, None, page, page_size)
    return {"items": _serialize_ledger(items), "total": total, "page": page, "page_size": page_size}


@router.post("/withdrawals")
async def request_withdrawal(body: WithdrawalRequestBody, user: CurrentUser = Depends(_publisher_only)):
    row = await financial_service.request_withdrawal(
        user.role, user.user_id, body.amount, body.idempotency_key, request_id_ctx.get()
    )
    return _serialize_withdrawal(row)


@router.get("/withdrawals")
async def list_my_withdrawals(
    status: str | None = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(_publisher_only),
):
    items, total = await financial_service.list_withdrawals(user.role, user.user_id, None, status, page, page_size)
    return {"items": [_serialize_withdrawal(w) for w in items], "total": total, "page": page, "page_size": page_size}


@router.get("/withdrawals/{withdrawal_id}")
async def get_my_withdrawal(withdrawal_id: str, user: CurrentUser = Depends(_publisher_only)):
    row = await financial_service.get_withdrawal(user.role, user.user_id, withdrawal_id)
    return _serialize_withdrawal(row)


@router.post("/withdrawals/{withdrawal_id}/cancel")
async def cancel_my_withdrawal(withdrawal_id: str, user: CurrentUser = Depends(_publisher_only)):
    row = await financial_service.cancel_withdrawal(user.role, user.user_id, withdrawal_id)
    return _serialize_withdrawal(row)


def _serialize_ledger(rows: list[dict]) -> list[dict]:
    return [
        {
            "ledger_id": r["ledger_id"],
            "transaction_type": r["transaction_type"],
            "direction": r["direction"],
            "amount": str(r["amount"]),
            "currency": r["currency"],
            "campaign_id": r.get("campaign_id"),
            "conversion_id": r.get("conversion_id"),
            "withdrawal_id": r.get("withdrawal_id"),
            "reference": r.get("reference"),
            "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else r["created_at"],
        }
        for r in rows
    ]


def _serialize_withdrawal(w: dict) -> dict:
    return {
        "withdrawal_id": w["withdrawal_id"],
        "publisher_id": w["publisher_id"],
        "manager_id": w.get("manager_id"),
        "amount": str(w["amount"]),
        "currency": w["currency"],
        "status": w["status"],
        "reference": w.get("reference"),
        "rejection_reason": w.get("rejection_reason"),
        "requested_at": w["requested_at"].isoformat() if hasattr(w["requested_at"], "isoformat") else w["requested_at"],
        "updated_at": w["updated_at"].isoformat() if hasattr(w["updated_at"], "isoformat") else w["updated_at"],
    }
