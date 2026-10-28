"""
PostgreSQL / Supabase connection pool - the financial system of record.
Raw asyncpg is used (not the Supabase SDK) because the earnings ledger needs
real multi-statement SQL transactions; see docs/ARCHITECTURE.md for the
reasoning, flagged as an open decision.

Startup fix (Part 1 review): unlike Motor, asyncpg.create_pool() actively
tries to open connections and raises immediately if it can't. That means a
hard try/except is required at startup so a down Postgres doesn't crash the
whole process (which would also take /health/live down with it). If the
initial attempt fails, `_pool` stays None and ping_postgres() retries pool
creation on every readiness check until it succeeds — self-healing without
needing a background task.
"""
import logging

import asyncpg

from app.config import get_settings
from app.storage import runtime

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _try_create_pool() -> asyncpg.Pool | None:
    settings = get_settings()
    try:
        pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=10)
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return pool
    except Exception as exc:  # noqa: BLE001 — caller decides how to handle a None result
        logger.warning("PostgreSQL not reachable (%s)", exc)
        return None


async def connect_to_postgres() -> None:
    global _pool
    if runtime.uses_adapter():
        return  # finance lives in the Supabase tables (financial_ledger / withdrawals)
    _pool = await _try_create_pool()
    if _pool is not None:
        logger.info("Connected to PostgreSQL")
    else:
        logger.warning("Starting up without PostgreSQL — will keep retrying via /health/ready")


async def close_postgres_connection() -> None:
    if runtime.uses_adapter():
        return
    if _pool is not None:
        await _pool.close()
        logger.info("PostgreSQL connection pool closed")


def get_pool() -> asyncpg.Pool:
    if runtime.uses_adapter():
        return runtime.get_adapter_pool()  # opaque pool; finance repositories route to the Supabase adapter
    if _pool is None:
        raise RuntimeError("PostgreSQL has not been initialized or is unreachable.")
    return _pool


async def ping_postgres() -> bool:
    global _pool
    if runtime.uses_adapter():
        return await runtime.get_adapter().ping()
    if _pool is None:
        # Self-healing retry: cheap to attempt, and this is exactly what
        # /health/ready is for — reflecting current reality, not a cached
        # startup failure.
        _pool = await _try_create_pool()
        return _pool is not None

    try:
        async with _pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 — health check must never raise
        return False
