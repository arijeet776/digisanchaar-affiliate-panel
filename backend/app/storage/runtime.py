"""
Storage backend selection.

    STORAGE_BACKEND=mongodb_supabase   (default) MongoDB + PostgreSQL/Supabase (direct drivers)
    STORAGE_BACKEND=supabase_rest      Supabase (PostgreSQL) over HTTPS/PostgREST only - no TCP driver

Everything backend-specific is reached through this module so the rest of the
code base (and the React frontend) never needs to know which one is active.
"""
from __future__ import annotations

from app.config import get_settings

BACKEND_MONGO_SUPABASE = "mongodb_supabase"
BACKEND_SUPABASE_REST = "supabase_rest"
VALID_BACKENDS = (BACKEND_MONGO_SUPABASE, BACKEND_SUPABASE_REST)

_adapter = None
_database = None
_pool = None


def uses_adapter() -> bool:
    """True when repositories are routed through the StorageAdapter (supabase_rest) instead of Motor/asyncpg."""
    return get_settings().storage_backend == BACKEND_SUPABASE_REST


def is_supabase_rest() -> bool:
    return get_settings().storage_backend == BACKEND_SUPABASE_REST


def get_adapter():
    global _adapter
    if _adapter is None:
        from app.storage.supabase_adapter import SupabaseRestAdapter

        s = get_settings()
        _adapter = SupabaseRestAdapter(s.supabase_url, s.supabase_service_key, timeout=s.supabase_timeout_seconds)
    return _adapter


def get_adapter_database():
    global _database
    if _database is None:
        from app.storage.mongo_compat import AdapterDatabase

        _database = AdapterDatabase(get_adapter())
    return _database


def get_adapter_pool():
    global _pool
    if _pool is None:
        from app.storage.finance_store import StorePool

        _pool = StorePool()
    return _pool


async def close() -> None:
    """Close the HTTP client (shutdown hook)."""
    global _adapter, _database, _pool
    if _adapter is not None and hasattr(_adapter._transport, "aclose"):
        await _adapter._transport.aclose()
    _adapter = _database = _pool = None


def reset_for_tests() -> None:
    global _adapter, _database, _pool
    _adapter = _database = _pool = None
