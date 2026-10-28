"""
Minimal SQL migration runner for the financial schema (Part 9). No ORM/
Alembic is introduced — this project has no other Postgres schema yet, so
a lightweight tracked-file-application runner is proportionate. Migrations
live in backend/migrations/*.sql, applied in filename order, each wrapped
in its own transaction, recorded in schema_migrations so re-running is a
no-op. Consistent with the rest of this app's startup philosophy: never
crash the process if Postgres is unreachable — log and let /health/ready
reflect reality (see app/db/postgres.py).
"""
import logging
import pathlib
import time

from app.db.postgres import get_pool

logger = logging.getLogger(__name__)

# "pending" (not attempted / Postgres was down), "ok", or "failed".
# Surfaced by /health/ready so a failed or skipped migration is never
# reported as a healthy instance.
status: str = "pending"
_last_attempt: float = 0.0
RETRY_COOLDOWN_SECONDS = 30.0

MIGRATION_LOCK_KEY = 727_001_013  # arbitrary app-wide advisory lock id
MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "migrations"


async def run_migrations() -> list[str]:
    """Returns the list of migration filenames applied THIS call (empty if none new)."""
    from app.storage import runtime

    if runtime.uses_adapter():
        # supabase_rest mode: the schema is installed once from backend/migrations/supabase/*.sql
        # in the Supabase SQL Editor; there are no runtime migrations to apply.
        return []
    pool = get_pool()
    applied: list[str] = []

    async with pool.acquire() as conn:
        # Serialise concurrent starters (multiple workers/replicas): only one
        # process applies migrations at a time; the others wait, then find
        # everything already recorded.
        await conn.execute("SELECT pg_advisory_lock($1)", MIGRATION_LOCK_KEY)
        try:
            return await _apply_pending(conn, applied)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", MIGRATION_LOCK_KEY)


async def _apply_pending(conn, applied: list[str]) -> list[str]:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    already = {r["filename"] for r in await conn.fetch("SELECT filename FROM schema_migrations")}

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in already:
            continue
        sql = path.read_text()
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute("INSERT INTO schema_migrations (filename) VALUES ($1)", path.name)
        applied.append(path.name)
        logger.info("Applied migration %s", path.name)

    return applied


async def run_migrations_safely() -> list[str]:
    global status, _last_attempt
    _last_attempt = time.monotonic()
    try:
        applied = await run_migrations()
        status = "ok"
        return applied
    except Exception as exc:  # noqa: BLE001 — startup must not crash if Postgres/migrations fail
        status = "failed"
        logger.error("PostgreSQL migrations FAILED — instance will report not_ready: %s", exc)
        return []


async def retry_if_needed() -> str:
    """Called from /health/ready when Postgres is reachable but migrations are
    not confirmed. Rate-limited so a persistently failing migration is not
    re-run on every probe."""
    if status != "ok" and (time.monotonic() - _last_attempt) >= RETRY_COOLDOWN_SECONDS:
        await run_migrations_safely()
    return status
