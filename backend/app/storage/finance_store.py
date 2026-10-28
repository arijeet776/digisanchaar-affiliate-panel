"""
Adapter-backed (Supabase REST) implementation of the finance repositories (ledger + withdrawals).

Semantics are identical to db/ledger_repository.py and db/withdrawal_repository.py:
* the ledger is APPEND-ONLY (the database refuses update/delete on it);
* wallet balance is ALWAYS computed from ledger rows (`ledger_summary`) - there is
  no stored/cached balance anywhere;
* a withdrawal request checks the balance AND inserts the withdrawal + hold row
  in one database transaction under a per-publisher advisory lock;
* every status transition is a single conditional update (atomic compare-and-set).
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from decimal import Decimal

from pymongo.errors import DuplicateKeyError

from app.core.exceptions import ConflictError, ServiceUnavailableError, ValidationAppError
from app.storage.runtime import get_adapter
from app.storage.storage_adapter import StorageApiError

logger = logging.getLogger(__name__)

LEDGER = "financial_ledger"
WITHDRAWALS = "withdrawals"
MIN_WITHDRAWAL = Decimal("100.00")
_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_ZERO = Decimal("0.00")


class StoreConn:
    """Opaque stand-in for an asyncpg connection (the repositories only pass it around)."""


class _Acquire:
    async def __aenter__(self):
        return StoreConn()

    async def __aexit__(self, *exc):
        return False


class StorePool:
    """Returned by db.postgres.get_pool() in supabase_rest mode."""

    def acquire(self):
        return _Acquire()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _q(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"))


def _is_ref(v) -> bool:
    return isinstance(v, str) and v.startswith("$")


def _ledger_id() -> str:
    return "LDG" + "".join(secrets.choice(_ALNUM) for _ in range(10))


def _withdrawal_id() -> str:
    return "WD" + "".join(secrets.choice(_ALNUM) for _ in range(10))


def _ledger_doc(*, idempotency_key, transaction_type, direction, publisher_id, amount, source, manager_id=None,
                campaign_id=None, conversion_id=None, withdrawal_id=None, reference=None, actor_user_id=None,
                request_id=None, metadata=None, now=None) -> dict:
    now = now or _now()
    return {
        "ledger_id": _ledger_id(), "idempotency_key": idempotency_key, "transaction_type": transaction_type,
        "direction": direction, "publisher_id": publisher_id, "manager_id": manager_id, "campaign_id": campaign_id,
        "conversion_id": conversion_id, "withdrawal_id": withdrawal_id, "amount": amount if _is_ref(amount) else _q(amount), "currency": "INR",
        "status": "posted", "source": source, "reference": reference, "actor_user_id": actor_user_id,
        "request_id": request_id, "metadata": metadata or {}, "created_at": now, "effective_at": now,
    }


# ------------------------------------------------------------------ ledger ----

async def insert_entry(conn, *, idempotency_key, transaction_type, direction, publisher_id, amount, source,
                       manager_id=None, campaign_id=None, conversion_id=None, withdrawal_id=None, reference=None,
                       actor_user_id=None, request_id=None, metadata=None):
    doc = _ledger_doc(idempotency_key=idempotency_key, transaction_type=transaction_type, direction=direction,
                      publisher_id=publisher_id, amount=amount, source=source, manager_id=manager_id,
                      campaign_id=campaign_id, conversion_id=conversion_id, withdrawal_id=withdrawal_id,
                      reference=reference, actor_user_id=actor_user_id, request_id=request_id, metadata=metadata)
    try:
        return await get_adapter().create(LEDGER, doc)
    except DuplicateKeyError:
        return None  # same contract as ON CONFLICT (idempotency_key) DO NOTHING


def _balance_from(s: dict) -> dict:
    return {
        "available_balance": s["total_credits"] - s["total_debits"],
        "total_earned": s["total_earned"],
        "total_reversed": s["total_reversed"],
        "held_amount": s["total_held_ever"] - s["total_released"],
        "currency": "INR",
    }


async def get_balance(conn, publisher_id: str) -> dict:
    return _balance_from(await get_adapter().ledger_summary({"publisher_id": publisher_id}))


async def list_entries(publisher_id, manager_id, transaction_type, skip, limit):
    flt: dict = {}
    if publisher_id:
        flt["publisher_id"] = publisher_id
    if manager_id:
        flt["manager_id"] = manager_id
    if transaction_type:
        flt["transaction_type"] = transaction_type
    return await get_adapter().query(LEDGER, flt, {"created_at": -1, "id": -1}, skip, limit)


async def network_overview() -> dict:
    s = await get_adapter().ledger_summary({})
    return {
        "total_publisher_liability": s["total_credits"] - s["total_debits"],
        "total_earned": s["total_earned"],
        "total_reversed": s["total_reversed"],
        "held_amount": s["total_held_ever"] - s["total_released"],
        "currency": "INR",
    }


async def get_earning_for_conversion(conn, conversion_id: str):
    return await get_adapter().find_one(LEDGER, {"conversion_id": conversion_id, "transaction_type": "earning"})


async def manager_scope_totals(conn, manager_id: str) -> dict:
    s = await get_adapter().ledger_summary({"manager_id": manager_id})
    return {"total_credits": s["total_credits"], "total_debits": s["total_debits"], "total_earned": s["total_earned"]}


# ------------------------------------------------------------- withdrawals ----

async def request_withdrawal(publisher_id, manager_id, amount: Decimal, idempotency_key, request_id) -> dict:
    if amount <= 0:
        raise ValidationAppError("Withdrawal amount must be greater than zero")
    if amount < MIN_WITHDRAWAL:
        raise ValidationAppError(f"Minimum withdrawal is ₹{MIN_WITHDRAWAL}")
    ad = get_adapter()
    if idempotency_key:
        existing = await ad.find_one(WITHDRAWALS, {"idempotency_key": idempotency_key})
        if existing:
            return existing
    wid, now, amount = _withdrawal_id(), _now(), _q(amount)
    ops = [
        {"op": "guard", "type": "balance_gte", "publisher_id": publisher_id, "amount": amount},
        {"op": "create", "table": WITHDRAWALS, "as": "w", "data": {
            "withdrawal_id": wid, "idempotency_key": idempotency_key, "publisher_id": publisher_id,
            "manager_id": manager_id, "amount": amount, "currency": "INR", "status": "requested",
            "requested_at": now, "updated_at": now}},
        {"op": "create", "table": LEDGER, "data": _ledger_doc(
            idempotency_key=f"withdrawal_hold:{wid}", transaction_type="withdrawal_hold", direction="debit",
            publisher_id=publisher_id, manager_id=manager_id, amount=amount, source="withdrawal_engine",
            withdrawal_id=wid, reference="Held pending withdrawal review", request_id=request_id, now=now)},
    ]
    try:
        results = await ad.batch(ops)
    except StorageApiError as exc:
        if exc.code == "INSUFFICIENT_BALANCE":
            bal = (await get_balance(None, publisher_id))["available_balance"]
            raise ValidationAppError(f"Requested amount exceeds available balance (₹{bal})") from exc
        raise
    except DuplicateKeyError:
        if idempotency_key:
            existing = await ad.find_one(WITHDRAWALS, {"idempotency_key": idempotency_key})
            if existing:
                return existing
        raise ConflictError("Duplicate withdrawal request")
    return results[1]


async def get_withdrawal(withdrawal_id: str):
    return await get_adapter().find_one(WITHDRAWALS, {"withdrawal_id": withdrawal_id})


async def list_withdrawals(publisher_id, manager_id, status, skip, limit):
    flt: dict = {}
    if publisher_id:
        flt["publisher_id"] = publisher_id
    if manager_id:
        flt["manager_id"] = manager_id
    if status:
        flt["status"] = status
    return await get_adapter().query(WITHDRAWALS, flt, {"requested_at": -1, "id": -1}, skip, limit)


async def _atomic_transition(withdrawal_id, from_statuses, to_status, **set_fields):
    set_fields.update(status=to_status, updated_at=_now())
    return await get_adapter().find_one_and_update(
        WITHDRAWALS, {"withdrawal_id": withdrawal_id, "status": {"$in": list(from_statuses)}},
        {"$set": set_fields}, return_after=True)


async def approve(withdrawal_id, reviewed_by):
    return await _atomic_transition(withdrawal_id, ["requested", "under_review"], "approved", reviewed_by=reviewed_by)


async def mark_under_review(withdrawal_id, reviewed_by):
    return await _atomic_transition(withdrawal_id, ["requested"], "under_review", reviewed_by=reviewed_by)


async def mark_paid(withdrawal_id, paid_by, reference):
    return await _atomic_transition(withdrawal_id, ["approved"], "paid", paid_by=paid_by, reference=reference)


async def _release(withdrawal_id: str, filters: dict, set_fields: dict, reference: str, actor_user_id: str | None):
    now = _now()
    ops = [
        {"op": "find_one_and_update", "table": WITHDRAWALS, "as": "w", "filters": filters,
         "update": {"$set": {**set_fields, "updated_at": now}}, "return_document": "after"},
        {"op": "create", "table": LEDGER, "if": "w", "data": _ledger_doc(
            idempotency_key=f"withdrawal_release:{withdrawal_id}", transaction_type="withdrawal_release",
            direction="credit", publisher_id="$w.publisher_id", manager_id="$w.manager_id", amount="$w.amount",
            source="withdrawal_engine", withdrawal_id=withdrawal_id, reference=reference,
            actor_user_id=actor_user_id, now=now)},
    ]
    # `amount` / `publisher_id` / `manager_id` are server-side references to the
    # row that was just transitioned, so release == the exact held amount.
    results = await get_adapter().batch(ops)
    return results[0]


async def reject(withdrawal_id, reviewed_by, reason):
    return await _release(
        withdrawal_id, {"withdrawal_id": withdrawal_id, "status": {"$in": ["requested", "under_review"]}},
        {"status": "rejected", "rejection_reason": reason, "reviewed_by": reviewed_by},
        f"Released — rejected: {reason}", reviewed_by)


async def cancel(withdrawal_id, publisher_id):
    return await _release(
        withdrawal_id, {"withdrawal_id": withdrawal_id, "publisher_id": publisher_id, "status": "requested"},
        {"status": "cancelled"}, "Released — cancelled by publisher", publisher_id)
