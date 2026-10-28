"""
Financial ledger repository. Every write here is an INSERT — nothing in
this module contains an UPDATE or DELETE against financial_ledger. Balance
is always computed live from the ledger (SUM of credits minus debits), not
stored, so there is never a second number that can drift from the truth.
"""
import logging
import secrets
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg

from app.core.exceptions import ConflictError, ServiceUnavailableError
from app.db.postgres import get_pool
from app.storage import runtime

logger = logging.getLogger(__name__)


def generate_ledger_id() -> str:
    return "LDG" + "".join(secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(10))


async def insert_entry(
    conn: asyncpg.Connection,
    *,
    idempotency_key: str,
    transaction_type: str,
    direction: str,
    publisher_id: str,
    amount: Decimal,
    source: str,
    manager_id: str | None = None,
    campaign_id: str | None = None,
    conversion_id: str | None = None,
    withdrawal_id: str | None = None,
    reference: str | None = None,
    actor_user_id: str | None = None,
    request_id: str | None = None,
    metadata: dict | None = None,
) -> dict | None:
    """
    Inserts one ledger row on the CALLER's connection/transaction (so a
    ledger write can be part of a larger atomic operation, e.g. a
    withdrawal request that also inserts/updates the withdrawals row).
    Returns None (not an error) if idempotency_key already exists — the
    caller decides whether that's an error or a harmless no-op retry.
    """
    if runtime.uses_adapter():
        from app.storage import finance_store

        return await finance_store.insert_entry(conn, idempotency_key=idempotency_key, transaction_type=transaction_type, direction=direction, publisher_id=publisher_id, amount=amount, source=source, manager_id=manager_id, campaign_id=campaign_id, conversion_id=conversion_id, withdrawal_id=withdrawal_id, reference=reference, actor_user_id=actor_user_id, request_id=request_id, metadata=metadata)
    ledger_id = generate_ledger_id()
    now = datetime.now(timezone.utc)
    import json

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO financial_ledger (
                ledger_id, idempotency_key, transaction_type, direction,
                publisher_id, manager_id, campaign_id, conversion_id, withdrawal_id,
                amount, currency, source, reference, actor_user_id, request_id, metadata,
                created_at, effective_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'INR',$11,$12,$13,$14,$15,$16,$16)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING *
            """,
            ledger_id, idempotency_key, transaction_type, direction,
            publisher_id, manager_id, campaign_id, conversion_id, withdrawal_id,
            amount, source, reference, actor_user_id, request_id,
            json.dumps(metadata or {}), now,
        )
    except asyncpg.PostgresError as exc:
        raise ServiceUnavailableError("Ledger write failed") from exc

    return dict(row) if row else None


async def get_balance(conn: asyncpg.Connection, publisher_id: str) -> dict:
    """
    Live-computed balance projection — never a stored column. `available`
    already reflects any held (requested/under_review) withdrawal amounts,
    since a withdrawal_hold debit is posted at request time.
    """
    if runtime.uses_adapter():
        from app.storage import finance_store

        return await finance_store.get_balance(conn, publisher_id)
    row = await conn.fetchrow(
        """
        SELECT
            COALESCE(SUM(amount) FILTER (WHERE direction = 'credit'), 0) AS total_credits,
            COALESCE(SUM(amount) FILTER (WHERE direction = 'debit'), 0) AS total_debits,
            COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'earning'), 0) AS total_earned,
            COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'earning_reversal'), 0) AS total_reversed,
            COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'withdrawal_hold'), 0) AS total_held_ever,
            COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'withdrawal_release'), 0) AS total_released
        FROM financial_ledger
        WHERE publisher_id = $1 AND status = 'posted'
        """,
        publisher_id,
    )
    available = row["total_credits"] - row["total_debits"]
    currently_held = row["total_held_ever"] - row["total_released"]
    return {
        "available_balance": available,
        "total_earned": row["total_earned"],
        "total_reversed": row["total_reversed"],
        "held_amount": currently_held,
        "currency": "INR",
    }


async def list_entries(
    publisher_id: str | None,
    manager_id: str | None,
    transaction_type: str | None,
    skip: int,
    limit: int,
) -> tuple[list[dict], int]:
    if runtime.uses_adapter():
        from app.storage import finance_store

        return await finance_store.list_entries(publisher_id, manager_id, transaction_type, skip, limit)
    pool = get_pool()
    conditions = []
    params: list = []

    def add(cond: str, value) -> None:
        params.append(value)
        conditions.append(cond.format(n=len(params)))

    if publisher_id:
        add("publisher_id = ${n}", publisher_id)
    if manager_id:
        add("manager_id = ${n}", manager_id)
    if transaction_type:
        add("transaction_type = ${n}", transaction_type)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    try:
        async with pool.acquire() as conn:
            total = await conn.fetchval(f"SELECT COUNT(*) FROM financial_ledger {where}", *params)
            rows = await conn.fetch(
                f"SELECT * FROM financial_ledger {where} ORDER BY created_at DESC LIMIT ${len(params)+1} OFFSET ${len(params)+2}",
                *params, limit, skip,
            )
        return [dict(r) for r in rows], total
    except asyncpg.PostgresError as exc:
        raise ServiceUnavailableError("Ledger read failed") from exc


async def network_overview() -> dict:
    """Super-Admin-scope aggregate — total liability/earned/held/reversed across all publishers."""
    if runtime.uses_adapter():
        from app.storage import finance_store

        return await finance_store.network_overview()
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COALESCE(SUM(amount) FILTER (WHERE direction = 'credit'), 0) AS total_credits,
                    COALESCE(SUM(amount) FILTER (WHERE direction = 'debit'), 0) AS total_debits,
                    COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'earning'), 0) AS total_earned,
                    COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'earning_reversal'), 0) AS total_reversed,
                    COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'withdrawal_hold'), 0) AS total_held_ever,
                    COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'withdrawal_release'), 0) AS total_released
                FROM financial_ledger WHERE status = 'posted'
                """
            )
        return {
            "total_publisher_liability": row["total_credits"] - row["total_debits"],
            "total_earned": row["total_earned"],
            "total_reversed": row["total_reversed"],
            "held_amount": row["total_held_ever"] - row["total_released"],
            "currency": "INR",
        }
    except asyncpg.PostgresError as exc:
        raise ServiceUnavailableError("Ledger read failed") from exc


async def get_earning_for_conversion(conn, conversion_id: str):
    """The original 'earning' ledger row of a conversion (None if there is none)."""
    if runtime.uses_adapter():
        from app.storage import finance_store

        return await finance_store.get_earning_for_conversion(conn, conversion_id)
    return await conn.fetchrow(
        "SELECT * FROM financial_ledger WHERE conversion_id = $1 AND transaction_type = 'earning'", conversion_id
    )


async def manager_scope_totals(conn, manager_id: str) -> dict:
    """Credits / debits / earned across the publishers of one manager."""
    if runtime.uses_adapter():
        from app.storage import finance_store

        return await finance_store.manager_scope_totals(conn, manager_id)
    row = await conn.fetchrow(
        """
        SELECT
            COALESCE(SUM(amount) FILTER (WHERE direction = 'credit'), 0) AS total_credits,
            COALESCE(SUM(amount) FILTER (WHERE direction = 'debit'), 0) AS total_debits,
            COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'earning'), 0) AS total_earned
        FROM financial_ledger WHERE manager_id = $1 AND status = 'posted'
        """,
        manager_id,
    )
    return dict(row)
