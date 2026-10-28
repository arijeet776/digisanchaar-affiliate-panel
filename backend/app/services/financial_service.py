"""
Part 9 — Financials + Payments business logic.

Scope boundary this module enforces (callers still gate role via
require_role; this module additionally enforces OWNERSHIP within a role):
- a Publisher may only ever query/act on their OWN publisher_id
- a Manager may only query publishers whose manager_id matches their own
- Super Admin has network-wide read and workflow authority

RBAC note (documented, not implemented further): the spec distinguishes
SUPER_ADMIN_OWNER (full financial authority) from SUPER_ADMIN. That tier
does not exist in this codebase yet (Role enum has three values — see
docs/ARCHITECTURE.md §30, carried over unchanged from Part 3). All
Super-Admin-gated financial actions in this module are therefore gated on
the existing Role.SUPER_ADMIN, matching how every other admin-only action
in this project already works. Introducing SUPER_ADMIN_OWNER as a fourth
role and re-gating specifically the highest-authority financial actions
behind it is additive and can be done later without touching this module's
logic — only its `require_role(...)` call sites.
"""
from decimal import Decimal, InvalidOperation

from app.core import audit_actions
from app.core.enums import Role
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationAppError
from app.db import ledger_repository, manager_repository, publisher_repository, withdrawal_repository
from app.db.audit_repository import record as audit_record
from app.db.postgres import get_pool

MIN_WITHDRAWAL = withdrawal_repository.MIN_WITHDRAWAL


async def _publisher_profile_for(user_id: str) -> dict:
    profile = await publisher_repository.get_publisher_by_user_id(user_id)
    if profile is None:
        raise NotFoundError("Publisher profile not found for current user")
    return profile


async def _manager_profile_for(user_id: str) -> dict:
    profile = await manager_repository.get_manager_by_user_id(user_id)
    if profile is None:
        raise NotFoundError("Manager profile not found for current user")
    return profile


async def _require_scope(actor_role: Role, actor_user_id: str, target_publisher_id: str) -> None:
    """Raises ForbiddenError unless actor_role/actor_user_id is authorized to act on target_publisher_id."""
    if actor_role == Role.SUPER_ADMIN:
        return
    if actor_role == Role.MANAGER:
        manager_profile = await _manager_profile_for(actor_user_id)
        target = await publisher_repository.get_publisher_by_publisher_id(target_publisher_id)
        if target is None or target["manager_id"] != manager_profile["manager_id"]:
            raise ForbiddenError("You do not have authority over this Publisher")
        return
    if actor_role == Role.PUBLISHER:
        own_profile = await _publisher_profile_for(actor_user_id)
        if own_profile["publisher_id"] != target_publisher_id:
            raise ForbiddenError("You may only access your own financial information")
        return
    raise ForbiddenError("Not authorized")


def to_money(value) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValidationAppError("Invalid monetary amount") from exc
    if d != d.quantize(Decimal("0.01")):
        raise ValidationAppError("Monetary amounts must have at most 2 decimal places")
    return d


# --- Earnings (called from the conversion engine, Part 6 integration point) ---

async def create_earning_for_conversion(
    *, conversion_id: str, publisher_id: str, manager_id: str | None,
    campaign_id: str | None, payout, request_id: str | None,
) -> dict | None:
    """
    Idempotent on conversion_id (unique idempotency_key). ₹0 is valid and
    still recorded (spec: "Install → ₹0" pattern) for a complete audit
    trail — it just has no balance effect. Returns the inserted row, or
    None if this conversion already has an earning (duplicate call).
    """
    if payout is None:
        return None
    amount = to_money(payout)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await ledger_repository.insert_entry(
            conn,
            idempotency_key=f"earning:{conversion_id}",
            transaction_type="earning",
            direction="credit",
            publisher_id=publisher_id,
            manager_id=manager_id,
            campaign_id=campaign_id,
            conversion_id=conversion_id,
            amount=amount,
            source="conversion_engine",
            reference="Conversion payout",
            actor_user_id="system",
            request_id=request_id,
        )
    if row:
        await audit_record(
            audit_actions.EARNING_CREATED, actor_user_id="system", target_user_id=None,
            after={"amount": str(amount), "conversion_id": conversion_id},
            metadata={"publisher_id": publisher_id, "campaign_id": campaign_id},
        )
    return row


async def reverse_earning(*, conversion_id: str, reason: str, actor_user_id: str) -> dict:
    """
    Admin-only compensating entry — the original earning row is NEVER
    edited (spec §10: "DO NOT edit the original ledger record. Create a
    compensating/reversal ledger entry."). Idempotent: a second reversal
    attempt for the same conversion is a no-op (same idempotency_key).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        original = await ledger_repository.get_earning_for_conversion(conn, conversion_id)
        if original is None:
            raise NotFoundError("No earning found for this conversion")

        row = await ledger_repository.insert_entry(
            conn,
            idempotency_key=f"reversal:{conversion_id}",
            transaction_type="earning_reversal",
            direction="debit",
            publisher_id=original["publisher_id"],
            manager_id=original["manager_id"],
            campaign_id=original["campaign_id"],
            conversion_id=conversion_id,
            amount=original["amount"],
            source="admin_manual",
            reference=reason,
            actor_user_id=actor_user_id,
        )
    if row is None:
        raise ValidationAppError("This conversion's earning has already been reversed")

    await audit_record(
        audit_actions.EARNING_REVERSED, actor_user_id=actor_user_id, target_user_id=None,
        before={"conversion_id": conversion_id}, after={"amount": str(original["amount"])}, reason=reason,
    )
    return dict(row)


# --- Wallet ---

async def get_wallet(actor_role: Role, actor_user_id: str, publisher_id: str) -> dict:
    await _require_scope(actor_role, actor_user_id, publisher_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        balance = await ledger_repository.get_balance(conn, publisher_id)
    money_keys = {"available_balance", "total_earned", "total_reversed", "held_amount"}
    return {
        "publisher_id": publisher_id,
        **{
            k: (str(v.quantize(Decimal("0.01"))) if k in money_keys and isinstance(v, Decimal) else v)
            for k, v in balance.items()
        },
    }


async def list_earnings(actor_role: Role, actor_user_id: str, publisher_id: str, page: int, page_size: int):
    await _require_scope(actor_role, actor_user_id, publisher_id)
    skip = (page - 1) * page_size
    items, total = await ledger_repository.list_entries(publisher_id, None, "earning", skip, page_size)
    return items, total


async def list_ledger(
    actor_role: Role, actor_user_id: str, publisher_id: str | None, manager_id: str | None,
    page: int, page_size: int,
):
    if actor_role == Role.PUBLISHER:
        own = await _publisher_profile_for(actor_user_id)
        publisher_id = own["publisher_id"]
    elif actor_role == Role.MANAGER:
        own_mgr = await _manager_profile_for(actor_user_id)
        manager_id = own_mgr["manager_id"]
        if publisher_id:
            await _require_scope(actor_role, actor_user_id, publisher_id)
    elif publisher_id:
        await _require_scope(actor_role, actor_user_id, publisher_id)

    skip = (page - 1) * page_size
    items, total = await ledger_repository.list_entries(publisher_id, manager_id, None, skip, page_size)
    return items, total


# --- Withdrawals ---

async def request_withdrawal(
    actor_role: Role, actor_user_id: str, amount, idempotency_key: str | None, request_id: str | None,
) -> dict:
    if actor_role != Role.PUBLISHER:
        raise ForbiddenError("Only a Publisher can request their own withdrawal")
    profile = await _publisher_profile_for(actor_user_id)
    money = to_money(amount)
    row = await withdrawal_repository.request_withdrawal(
        profile["publisher_id"], profile["manager_id"], money, idempotency_key, request_id
    )
    await audit_record(
        audit_actions.WITHDRAWAL_REQUESTED, actor_user_id=actor_user_id, target_user_id=None,
        after={"withdrawal_id": row["withdrawal_id"], "amount": str(money)},
        metadata={"publisher_id": profile["publisher_id"]},
    )
    return row


async def get_withdrawal(actor_role: Role, actor_user_id: str, withdrawal_id: str) -> dict:
    row = await withdrawal_repository.get_withdrawal(withdrawal_id)
    if row is None:
        raise NotFoundError("Withdrawal not found")
    await _require_scope(actor_role, actor_user_id, row["publisher_id"])
    return row


async def list_withdrawals(
    actor_role: Role, actor_user_id: str, publisher_id: str | None, status: str | None, page: int, page_size: int,
):
    manager_id = None
    if actor_role == Role.PUBLISHER:
        own = await _publisher_profile_for(actor_user_id)
        publisher_id = own["publisher_id"]
    elif actor_role == Role.MANAGER:
        own_mgr = await _manager_profile_for(actor_user_id)
        manager_id = own_mgr["manager_id"]
        if publisher_id:
            await _require_scope(actor_role, actor_user_id, publisher_id)
    elif publisher_id:
        await _require_scope(actor_role, actor_user_id, publisher_id)

    skip = (page - 1) * page_size
    items, total = await withdrawal_repository.list_withdrawals(publisher_id, manager_id, status, skip, page_size)
    return items, total


async def cancel_withdrawal(actor_role: Role, actor_user_id: str, withdrawal_id: str) -> dict:
    if actor_role != Role.PUBLISHER:
        raise ForbiddenError("Only the requesting Publisher can cancel a withdrawal")
    profile = await _publisher_profile_for(actor_user_id)
    row = await withdrawal_repository.cancel(withdrawal_id, profile["publisher_id"])
    if row is None:
        raise ValidationAppError("Withdrawal cannot be cancelled (not found, not yours, or no longer pending)")
    await audit_record(
        audit_actions.WITHDRAWAL_CANCELLED, actor_user_id=actor_user_id, target_user_id=None,
        after={"withdrawal_id": withdrawal_id},
    )
    return row


async def _require_admin_or_scoped_manager(actor_role: Role, actor_user_id: str, withdrawal_row: dict) -> None:
    if actor_role == Role.SUPER_ADMIN:
        return
    if actor_role == Role.MANAGER:
        own_mgr = await _manager_profile_for(actor_user_id)
        if withdrawal_row["manager_id"] != own_mgr["manager_id"]:
            raise ForbiddenError("You do not have authority over this Publisher's withdrawal")
        return
    raise ForbiddenError("Not authorized")


async def approve_withdrawal(actor_role: Role, actor_user_id: str, withdrawal_id: str) -> dict:
    existing = await withdrawal_repository.get_withdrawal(withdrawal_id)
    if existing is None:
        raise NotFoundError("Withdrawal not found")
    await _require_admin_or_scoped_manager(actor_role, actor_user_id, existing)

    row = await withdrawal_repository.approve(withdrawal_id, actor_user_id)
    if row is None:
        raise ValidationAppError(f"Withdrawal cannot be approved from its current state ({existing['status']})")
    await audit_record(
        audit_actions.WITHDRAWAL_APPROVED, actor_user_id=actor_user_id, target_user_id=None,
        before={"status": existing["status"]}, after={"status": "approved"},
        metadata={"withdrawal_id": withdrawal_id},
    )
    return row


async def reject_withdrawal(actor_role: Role, actor_user_id: str, withdrawal_id: str, reason: str) -> dict:
    if not reason or not reason.strip():
        raise ValidationAppError("A rejection reason is required")
    existing = await withdrawal_repository.get_withdrawal(withdrawal_id)
    if existing is None:
        raise NotFoundError("Withdrawal not found")
    await _require_admin_or_scoped_manager(actor_role, actor_user_id, existing)

    row = await withdrawal_repository.reject(withdrawal_id, actor_user_id, reason.strip())
    if row is None:
        raise ValidationAppError(f"Withdrawal cannot be rejected from its current state ({existing['status']})")
    await audit_record(
        audit_actions.WITHDRAWAL_REJECTED, actor_user_id=actor_user_id, target_user_id=None,
        before={"status": existing["status"]}, after={"status": "rejected"}, reason=reason,
        metadata={"withdrawal_id": withdrawal_id},
    )
    return row


async def mark_withdrawal_paid(actor_role: Role, actor_user_id: str, withdrawal_id: str, reference: str | None) -> dict:
    # Payment marking is Super-Admin-only (financial disbursement authority) —
    # a Manager can approve/reject their own scope but not confirm money left the building.
    if actor_role != Role.SUPER_ADMIN:
        raise ForbiddenError("Only Super Admin can mark a withdrawal as paid")
    existing = await withdrawal_repository.get_withdrawal(withdrawal_id)
    if existing is None:
        raise NotFoundError("Withdrawal not found")

    row = await withdrawal_repository.mark_paid(withdrawal_id, actor_user_id, reference)
    if row is None:
        raise ValidationAppError(f"Withdrawal cannot be marked paid from its current state ({existing['status']})")
    await audit_record(
        audit_actions.WITHDRAWAL_PAID, actor_user_id=actor_user_id, target_user_id=None,
        before={"status": existing["status"]}, after={"status": "paid", "reference": reference},
        metadata={"withdrawal_id": withdrawal_id},
    )
    return row


# --- Admin overview ---

async def network_overview(actor_role: Role) -> dict:
    if actor_role != Role.SUPER_ADMIN:
        raise ForbiddenError("Not authorized")
    overview = await ledger_repository.network_overview()
    pending, _ = await withdrawal_repository.list_withdrawals(None, None, "requested", 0, 1)
    approved, _ = await withdrawal_repository.list_withdrawals(None, None, "approved", 0, 1)
    paid, _ = await withdrawal_repository.list_withdrawals(None, None, "paid", 0, 1)
    rejected, _ = await withdrawal_repository.list_withdrawals(None, None, "rejected", 0, 1)
    _, pending_total = await withdrawal_repository.list_withdrawals(None, None, "requested", 0, 1)
    _, approved_total = await withdrawal_repository.list_withdrawals(None, None, "approved", 0, 1)
    _, paid_total = await withdrawal_repository.list_withdrawals(None, None, "paid", 0, 1)
    _, rejected_total = await withdrawal_repository.list_withdrawals(None, None, "rejected", 0, 1)
    return {
        **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in overview.items()},
        "withdrawals_pending_count": pending_total,
        "withdrawals_approved_count": approved_total,
        "withdrawals_paid_count": paid_total,
        "withdrawals_rejected_count": rejected_total,
    }


async def manager_overview(actor_role: Role, actor_user_id: str) -> dict:
    if actor_role != Role.MANAGER:
        raise ForbiddenError("Not authorized")
    own_mgr = await _manager_profile_for(actor_user_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await ledger_repository.manager_scope_totals(conn, own_mgr["manager_id"])
    return {
        "manager_id": own_mgr["manager_id"],
        "scoped_publisher_liability": str(row["total_credits"] - row["total_debits"]),
        "scoped_total_earned": str(row["total_earned"]),
        "currency": "INR",
    }


# --- Manual adjustment (Super Admin only) ---

async def create_adjustment(
    actor_role: Role, actor_user_id: str, publisher_id: str, amount, direction: str, reason: str,
) -> dict:
    if actor_role != Role.SUPER_ADMIN:
        raise ForbiddenError("Only Super Admin can create a manual financial adjustment")
    if direction not in ("credit", "debit"):
        raise ValidationAppError("direction must be 'credit' or 'debit'")
    if not reason or not reason.strip():
        raise ValidationAppError("A reason is required for a manual adjustment")

    target = await publisher_repository.get_publisher_by_publisher_id(publisher_id)
    if target is None:
        raise NotFoundError("Publisher not found")

    money = to_money(amount)
    import uuid

    idem_key = f"adjustment:{uuid.uuid4().hex}"
    transaction_type = "adjustment_credit" if direction == "credit" else "adjustment_debit"

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await ledger_repository.insert_entry(
            conn,
            idempotency_key=idem_key,
            transaction_type=transaction_type,
            direction=direction,
            publisher_id=publisher_id,
            manager_id=target.get("manager_id"),
            amount=money,
            source="admin_manual",
            reference=reason.strip(),
            actor_user_id=actor_user_id,
        )
    await audit_record(
        audit_actions.FINANCIAL_ADJUSTMENT_CREATED, actor_user_id=actor_user_id, target_user_id=None,
        after={"publisher_id": publisher_id, "amount": str(money), "direction": direction}, reason=reason,
    )
    return dict(row)
