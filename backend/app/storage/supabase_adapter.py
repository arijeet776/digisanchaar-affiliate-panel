"""
SupabaseRestAdapter - Supabase (PostgreSQL) over HTTPS ONLY (PostgREST), no TCP driver.

Every storage operation is ONE call to the Postgres function `qx_exec(req jsonb)`
(see migrations/supabase/001_schema.sql) through
    POST {SUPABASE_URL}/rest/v1/rpc/qx_exec
so a request is one round trip and one database transaction (batch = atomic,
withdrawals are serialised per publisher with an advisory lock). It speaks the
same wire protocol as the shared BaseStorageAdapter, so the repositories, the
Motor-compatible facade (mongo_compat.AdapterDatabase), the finance code and the
codec are reused unchanged.

Security
* Needs the SERVER-SIDE secret / service_role key (env SUPABASE_SERVICE_KEY).
  The publishable/anon key is refused at start-up (config guard) - with RLS on it
  could not read anything, and it must never be used for server data access.
* The key is sent only in the `apikey` header (and `Authorization` for legacy JWT
  keys); it is never logged, never placed in a URL, and __repr__ hides it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

from app.core.exceptions import ServiceUnavailableError
from app.storage import codec
from app.storage.storage_adapter import (
    _RETRY_DELAYS, BaseStorageAdapter, TransientStorageError, _decode_op_result, _encode_with_refs, _record_call,
)

logger = logging.getLogger(__name__)

RPC_PATH = "/rest/v1/rpc/qx_exec"
PURGE_RPC_PATH = "/rest/v1/rpc/qx_purge_campaign"  # migrations/supabase/002_campaign_purge.sql


class PostgrestTransport:
    """httpx transport with connection keep-alive (a warm call is one HTTPS request)."""

    def __init__(self, base_url: str, key: str, timeout: float = 15.0):
        self._base = base_url.rstrip("/")
        self._url = self._base + RPC_PATH
        self._timeout = timeout
        self._headers = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json"}
        if key.startswith("eyJ"):  # legacy JWT service_role key; new sb_secret_* keys go in `apikey` only
            self._headers["Authorization"] = f"Bearer {key}"
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=self._timeout, headers=self._headers,
                                             limits=httpx.Limits(max_keepalive_connections=20, max_connections=50))
        return self._client

    async def __call__(self, _url: str, payload: dict) -> dict:
        import httpx

        client = self._get_client()
        try:
            # _url is the RPC path to call (qx_exec by default, or another function such as qx_purge_campaign).
            url = self._base + (_url or RPC_PATH)
            resp = await client.post(url, content=json.dumps(payload))
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise TransientStorageError("connection failed", applied=False) from exc
        except httpx.HTTPError as exc:
            raise TransientStorageError("request failed", applied=True) from exc
        if resp.status_code >= 500 or resp.status_code == 429:
            raise TransientStorageError(f"upstream status {resp.status_code}", applied=True)
        if resp.status_code in (401, 403):
            return {"success": False, "error": {"code": "UNAUTHORIZED", "message": "Storage key rejected"}}
        if resp.status_code >= 400:  # e.g. 404 = function/schema not installed (migration not run)
            return {"success": False, "error": {"code": "NOT_CONFIGURED", "message": "Storage schema not installed"}}
        try:
            return resp.json()
        except ValueError as exc:
            raise TransientStorageError("non-JSON response from the storage API", applied=True) from exc

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _prep(value: Any) -> Any:
    """Wire preparation: `sort` dicts become ordered [field, dir] pairs (JSONB would reorder object keys)."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "sort" and isinstance(v, dict):
                out[k] = [[f, d] for f, d in v.items()]
            else:
                out[k] = _prep(v)
        return out
    if isinstance(value, list):
        return [_prep(v) for v in value]
    return value


class SupabaseRestAdapter(BaseStorageAdapter):
    def __init__(self, project_url: str, key: str, transport: Callable[[str, dict], Awaitable[dict]] | None = None,
                 timeout: float = 15.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        if not project_url or not project_url.startswith("https://"):
            raise ValueError("SUPABASE_URL must be the https project URL")
        if not key:
            raise ValueError("SUPABASE_SERVICE_KEY is not configured")
        self._base = project_url.rstrip("/")
        self._transport = transport or PostgrestTransport(self._base, key, timeout)
        self._sleep = sleep
        self._secret = ""  # unused; keeps the parent's attribute contract

    def __repr__(self) -> str:  # never expose the key
        return "<SupabaseRestAdapter>"

    async def purge_campaign(self, campaign_id: str, actor_user_id: str | None) -> dict:
        """Hard purge of ONE settled campaign: a single database transaction (see 002_campaign_purge.sql).
        Returns the per-table row counts. Any failure means the database rolled everything back."""
        result = await self._transport(PURGE_RPC_PATH, {"p_campaign_id": campaign_id, "p_actor": actor_user_id})
        if not isinstance(result, dict) or result.get("success") is False or "error" in result:
            logger.error("Campaign purge rejected or failed; nothing was deleted (%s)",
                         (result or {}).get("error", {}).get("code") if isinstance(result, dict) else "bad response")
            raise ServiceUnavailableError("Purge was refused or failed; nothing was deleted. Check the campaign state and retry.")
        return result

    async def _call(self, url: str, body: dict, *, write: bool) -> dict:
        payload = {"req": _prep(body)}
        last: Exception | None = None
        for attempt in range(len(_RETRY_DELAYS) + 1):
            t0 = time.perf_counter()
            try:
                result = await self._transport(RPC_PATH, payload)
            except TransientStorageError as exc:
                last = exc
                if write and exc.applied:
                    raise ServiceUnavailableError("Storage temporarily unavailable") from exc
            else:
                return result
            finally:
                _record_call(t0)
            if attempt < len(_RETRY_DELAYS):
                await self._sleep(_RETRY_DELAYS[attempt])
        logger.warning("Supabase API unavailable after retries (%s)", type(last).__name__)
        raise ServiceUnavailableError("Storage temporarily unavailable")

    async def _ok(self, table: dict, body: dict, *, write: bool) -> dict:
        result = await self._call(RPC_PATH, {"table": table["collection"], **body}, write=write)
        if not result.get("success"):
            self._raise(result)
        return result

    # No 1-cell size limit in Postgres: values are stored as-is.
    async def _spill(self, table: dict, doc: dict) -> dict:
        return doc

    async def _resolve_blobs(self, docs: list[dict]) -> list[dict]:
        return docs

    async def ping(self) -> bool:
        try:
            result = await self._call(RPC_PATH, {"action": "ping"}, write=False)
            return bool(result.get("success"))
        except Exception:  # noqa: BLE001 - health probes must never raise
            return False

    async def initialize(self) -> dict:
        """Nothing to create at runtime: the schema is installed once from the SQL migration."""
        return {"ok": await self.ping()}

    async def batch(self, operations):
        wire, tables = [], []
        for op in operations:
            op = dict(op)
            if op["op"] == "guard":
                tables.append(codec.table_def("financial_ledger"))
                if "amount" in op:
                    op["amount"] = codec.money_text(op["amount"])
                wire.append(op)
                continue
            t = codec.table_def(op["table"])
            tables.append(t)
            op["table"] = t["collection"]
            if "data" in op and op["op"] == "create":
                op["data"] = _encode_with_refs(t, op["data"])
            if "filters" in op:
                op["filters"] = codec.encode_filter(t, op["filters"])
            if "update" in op:
                op["update"] = codec.encode_update(t, op["update"])
            wire.append(op)
        result = await self._call(RPC_PATH, {"action": "batch", "operations": wire}, write=True)
        if not result.get("success"):
            self._raise(result)
        return [_decode_op_result(op, t, r) for op, t, r in zip(operations, tables, result["data"])]
