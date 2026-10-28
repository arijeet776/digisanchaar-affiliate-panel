"""
Withdrawal workflow. The critical correctness property — no double
withdrawal, no race between two concurrent requests — comes from a
Postgres advisory transaction lock keyed per-publisher
(`pg_advisory_xact_lock(hashtext(publisher_id))`), held for the duration of
the single transaction that both checks available balance AND inserts the
withdrawal_hold ledger entry. Two concurrent requests for the same
publisher serialize on that lock; the second one recomputes balance AFTER
the first committed, so it correctly sees the reduced balance.

Every status transition (approve/reject/pay/cancel) is a single
conditional UPDATE ... WHERE status = <expected> ... RETURNING *, the same
atomic-transition pattern used throughout this project (Part 2's
onboarding approvals, Part 3's campaign lifecycle) — only one concurrent
call can ever match and transition a given row.
"""
import logging
import secrets
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg

from app.core.exceptions import ConflictError, ServiceUnavailableError, ValidationAppError
from app.db import ledger_repository
from app.db.postgres import get_pool
from app.storage import runtime

logger = logging.getLogger(__name__)

MIN_WITHDRAWAL = Decimal("100.00")


def generate_withdrawal_id() -> str:
    return "WD" + "".join(secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(10))


async def request_withdrawal(
    publisher_id: str,
    manager_id: str | None,
    amount: Decimal,
    idempotency_key: str | None,
    request_id: str | None,
) -> dict:
    if runtime.uses_adapter():
        from app.storage import finance_store

        return await finance_store.request_withdrawal(publisher_id, manager_id, amount, idempotency_key, request_id)
    if amount <= 0:
        raise ValidationAppError("Withdrawal amount must be greater than zero")
    if amount < MIN_WITHDRAWAL:
        raise ValidationAppError(f"Minimum withdrawal is ₹{MIN_WITHDRAWAL}")

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Serializes concurrent requests for the SAME publisher only;
                # released automatically at transaction end.
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", publisher_id)

                if idempotency_key:
                    existing = await conn.fetchrow(
                        "SELECT * FROM withdrawals WHERE idempotency_key = $1", idempotency_key
                    )
                    if existing:
                        return dict(existing)

                balance = await ledger_repository.get_balance(conn, publisher_id)
                if amount > balance["available_balance"]:
                    raise ValidationAppError(
                        f"Requested amount exceeds available balance (₹{balance['available_balance']})"
                    )

                withdrawal_id = generate_withdrawal_id()
                now = datetime.now(timezone.utc)
                row = await conn.fetchrow(
                    """
                    INSERT INTO withdrawals (
                        withdrawal_id, idempotency_key, publisher_id, manager_id,
                        amount, currency, status, requested_at, updated_at
                    ) VALUES ($1,$2,$3,$4,$5,'INR','requested',$6,$6)
                    RETURNING *
                    """,
                    withdrawal_id, idempotency_key, publisher_id, manager_id, amount, now,
                )

                await ledger_repository.insert_entry(
                    conn,
                    idempotency_key=f"withdrawal_hold:{withdrawal_id}",
                    transaction_type="withdrawal_hold",
                    direction="debit",
                    publisher_id=publisher_id,
                    manager_id=manager_id,
                    amount=amount,
                    source="withdrawal_engine",
                    withdrawal_id=withdrawal_id,
                    reference="Held pending withdrawal review",
                    request_id=request_id,
                )
                return dict(row)
    except asyncpg.UniqueViolationError:
        async with pool.acquire() as conn:
            existing = await conn.fetchrow("SELECT * FROM withdrawals WHERE idempotency_key = $1", idempotency_key)
            if existing:
                return dict(existing)
        raise ConflictError("Duplicate withdrawal request")
    except asyncpg.PostgresError as exc:
        if isinstance(exc, asyncpg.CheckViolationError):
            raise ValidationAppError("Invalid withdrawal amount") from exc
        raise ServiceUnavailableError("Withdrawal store unavailable") from exc


async def get_withdrawal(withdrawal_id: str) -> dict | None:
    if runtime.uses_adapter():
        from app.storage import finance_store

        return await finance_store.get_withdrawal(withdrawal_id)
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM withdrawals WHERE withdrawal_id = $1", withdrawal_id)
        return dict(row) if row else None
    except asyncpg.PostgresError as exc:
        raise ServiceUnavailableError("Withdrawal store unavailable") from exc


async def list_withdrawals(
    publisher_id: str | None, manager_id: str | None, status: str | None, skip: int, limit: int
) -> tuple[list[dict], int]:
    if runtime.uses_adapter():
        from app.storage import finance_store

        return await finance_store.list_withdrawals(publisher_id, manager_id, status, skip, limit)
    pool = get_pool()
    conditions, params = [], []

    def add(cond: str, value) -> None:
        params.append(value)
        conditions.append(cond.format(n=len(params)))

    if publisher_id:
        add("publisher_id = ${n}", publisher_id)
    if manager_id:
        add("manager_id = ${n}", manager_id)
    if status:
        add("status = ${n}", status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    try:
        async with pool.acquire() as conn:
            total = await conn.fetchval(f"SELECT COUNT(*) FROM withdrawals {where}", *params)
            rows = await conn.fetch(
                f"SELECT * FROM withdrawals {where} ORDER BY requested_at DESC LIMIT ${len(params)+1} OFFSET ${len(params)+2}",
                *params, limit, skip,
            )
        return [dict(r) for r in rows], total
    except asyncpg.PostgresError as exc:
        raise ServiceUnavailableError("Withdrawal store unavailable") from exc


async def _atomic_transition(withdrawal_id: str, from_statuses: list[str], to_status: str, **set_fields) -> dict | None:
    if runtime.uses_adapter():
        from app.storage import finance_store

        return await finance_store._atomic_transition(withdrawal_id, from_statuses, to_status, **set_fields)
    pool = get_pool()
    now = datetime.now(timezone.utc)
    set_fields["updated_at"] = now
    set_fields["status"] = to_status

    cols = list(set_fields.keys())
    values = [set_fields[c] for c in cols]
    set_clause = ", ".join(f"{c} = ${i+2}" for i, c in enumerate(cols))
    status_list_sql = ", ".join(f"${len(values)+2+i}" for i in range(len(from_statuses)))
    params = [withdrawal_id, *values, *from_statuses]

    sql = f"""
        UPDATE withdrawals
        SET {set_clause}
        WHERE withdrawal_id = $1 AND status IN ({status_list_sql})
        RETURNING *
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
        return dict(row) if row else None
    except asyncpg.PostgresError as exc:
        raise ServiceUnavailableError("Withdrawal store unavailable") from exc


async def approve(withdrawal_id: str, reviewed_by: str) -> dict | None:
    return await _atomic_transition(withdrawal_id, ["requested", "under_review"], "approved", reviewed_by=reviewed_by)


async def mark_under_review(withdrawal_id: str, reviewed_by: str) -> dict | None:
    return await _atomic_transition(withdrawal_id, ["requested"], "under_review", reviewed_by=reviewed_by)


async def mark_paid(withdrawal_id: str, paid_by: str, reference: str | None) -> dict | None:
    return await _atomic_transition(withdrawal_id, ["approved"], "paid", paid_by=paid_by, reference=reference)


async def reject(withdrawal_id: str, reviewed_by: str, reason: str) -> dict | None:
    """Rejection also releases the held funds — done atomically in one DB transaction."""
    if runtime.uses_adapter():
        from app.storage import finance_store

        return await finance_store.reject(withdrawal_id, reviewed_by, reason)
    pool = get_pool()
    now = datetime.now(timezone.utc)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    UPDATE withdrawals
                    SET status = 'rejected', rejection_reason = $2, reviewed_by = $3, updated_at = $4
                    WHERE withdrawal_id = $1 AND status IN ('requested', 'under_review')
                    RETURNING *
                    """,
                    withdrawal_id, reason, reviewed_by, now,
                )
                if row is None:
                    return None
                await ledger_repository.insert_entry(
                    conn,
                    idempotency_key=f"withdrawal_release:{withdrawal_id}",
                    transaction_type="withdrawal_release",
                    direction="credit",
                    publisher_id=row["publisher_id"],
                    manager_id=row["manager_id"],
                    amount=row["amount"],
                    source="withdrawal_engine",
                    withdrawal_id=withdrawal_id,
                    reference=f"Released — rejected: {reason}",
                    actor_user_id=reviewed_by,
                )
                return dict(row)
    except asyncpg.PostgresError as exc:
        raise ServiceUnavailableError("Withdrawal store unavailable") from exc


async def cancel(withdrawal_id: str, publisher_id: str) -> dict | None:
    """Publisher-initiated cancellation — only while still 'requested', and only their own."""
    if runtime.uses_adapter():
        from app.storage import finance_store

        return await finance_store.cancel(withdrawal_id, publisher_id)
    pool = get_pool()
    now = datetime.now(timezone.utc)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    UPDATE withdrawals
                    SET status = 'cancelled', updated_at = $3
                    WHERE withdrawal_id = $1 AND publisher_id = $2 AND status = 'requested'
                    RETURNING *
                    """,
                    withdrawal_id, publisher_id, now,
                )
                if row is None:
                    return None
                await ledger_repository.insert_entry(
                    conn,
                    idempotency_key=f"withdrawal_release:{withdrawal_id}",
                    transaction_type="withdrawal_release",
                    direction="credit",
                    publisher_id=row["publisher_id"],
                    manager_id=row["manager_id"],
                    amount=row["amount"],
                    source="withdrawal_engine",
                    withdrawal_id=withdrawal_id,
                    reference="Released — cancelled by publisher",
                    actor_user_id=publisher_id,
                )
                return dict(row)
    except asyncpg.PostgresError as exc:
        raise ServiceUnavailableError("Withdrawal store unavailable") from exc
