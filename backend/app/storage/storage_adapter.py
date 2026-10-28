"""
BaseStorageAdapter - the storage-neutral query/write logic shared by the Supabase REST adapter
(storage/supabase_adapter.py supplies the transport and the `_call` / `_ok` / `batch` methods).

Only tables declared in storage/schema.py can be addressed. Reads are retried on transient
failures with backoff; writes are retried ONLY when the server provably did not apply them, so a
retry can never double-apply a write.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from typing import Any, Awaitable, Callable

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.exceptions import ServiceUnavailableError, ValidationAppError
from app.storage import codec
from app.storage.interface import StorageAdapter

logger = logging.getLogger(__name__)

PAGE = 1000                    # rows per page when reading
_RETRY_DELAYS = (0.4, 1.2, 3.0)

Transport = Callable[[str, dict], Awaitable[dict]]


class TransientStorageError(Exception):
    """Network / storage infrastructure problem; `applied` says whether the
    request may have been executed server-side."""

    def __init__(self, message: str, applied: bool):
        super().__init__(message)
        self.applied = applied


class StorageApiError(Exception):
    def __init__(self, code: str, message: str, payload: dict | None = None):
        super().__init__(message)
        self.code = code
        self.payload = payload or {}


# Per-request counters (storage calls made and time spent), surfaced by the API as a
# `Server-Timing` header so dashboard latency can be measured instead of guessed.
_REQ_STATS: contextvars.ContextVar = contextvars.ContextVar("storage_req_stats", default=None)


def begin_request_stats() -> dict:
    stats = {"calls": 0, "ms": 0.0}
    _REQ_STATS.set(stats)
    return stats


def _record_call(t0: float) -> None:
    stats = _REQ_STATS.get()
    if stats is not None:
        stats["calls"] += 1
        stats["ms"] += (time.perf_counter() - t0) * 1000.0


class BaseStorageAdapter(StorageAdapter):


    # -------------------------------------------------------------- plumbing --


    def _raise(self, result: dict) -> None:
        err = (result or {}).get("error") or {}
        code, message = err.get("code", "ERROR"), err.get("message", "Storage error")
        if code == "DUPLICATE_KEY":
            raise DuplicateKeyError(message)
        if code in ("VALIDATION_ERROR", "VALUE_TOO_LONG", "INSUFFICIENT_BALANCE", "FORBIDDEN_TABLE_OPERATION"):
            raise StorageApiError(code, message, err)
        if code in ("UNAUTHORIZED", "NOT_CONFIGURED", "INVALID_TABLE", "INVALID_ACTION", "SCHEMA_CONFLICT"):
            logger.error("Storage API refused the request: %s", code)
            raise ServiceUnavailableError("Storage is not configured correctly")
        if code == "SERVER_BUSY":
            raise ServiceUnavailableError("Storage is busy, please retry")
        raise StorageApiError(code, message, err)


    # ----------------------------------------------------------- large values --


    async def _spill(self, table: dict, doc: dict) -> dict:
        return doc  # Postgres has no per-cell size limit: values are stored as-is

    async def _resolve_blobs(self, docs: list[dict]) -> list[dict]:
        return docs

    def _decode(self, table: dict, docs: list[dict]) -> list[dict]:
        return [codec.decode_doc(table, d) for d in docs]

    # ----------------------------------------------------------------- reads --


    async def get(self, table, id, projection=None):
        t = codec.table_def(table)
        res = await self._ok(t, {"action": "get", "id": str(id), **({"projection": projection} if projection else {})}, write=False)
        if res["data"] is None:
            return None
        doc = (await self._resolve_blobs([codec.decode_doc(t, res["data"])]))[0]
        return doc

    async def find_one(self, table, filters=None, sort=None, projection=None):
        t = codec.table_def(table)
        body = {"action": "find_one", "filters": codec.encode_filter(t, filters)}
        if sort:
            body["sort"] = codec.encode_sort(sort)
        if projection:
            body["projection"] = projection
        res = await self._ok(t, body, write=False)
        if res["data"] is None:
            return None
        return (await self._resolve_blobs([codec.decode_doc(t, res["data"])]))[0]

    async def query(self, table, filters=None, sort=None, skip=0, limit=100, projection=None):
        t = codec.table_def(table)
        flt = codec.encode_filter(t, filters)
        srt = codec.encode_sort(sort)
        out: list[dict] = []
        total = 0
        want = limit if limit and limit > 0 else None
        cur = skip
        while True:
            page = PAGE if want is None else min(PAGE, want - len(out))
            if page <= 0:
                break
            body = {"action": "query", "filters": flt, "skip": cur, "limit": page}
            if srt:
                body["sort"] = srt
            if projection:
                body["projection"] = projection
            res = await self._ok(t, body, write=False)
            total = res["pagination"]["total"]
            out.extend(res["data"])
            cur += len(res["data"])
            if len(res["data"]) < page or cur >= total:
                break
        docs = await self._resolve_blobs(self._decode(t, out))
        return docs, total

    async def list(self, table, filters=None, page=1, limit=100):
        docs, total = await self.query(table, filters, None, (page - 1) * limit, limit)
        return docs, {"page": page, "limit": limit, "total": total, "pages": -(-total // limit) if limit else 0}

    async def count(self, table, filters=None):
        t = codec.table_def(table)
        res = await self._ok(t, {"action": "count", "filters": codec.encode_filter(t, filters)}, write=False)
        return int(res["data"]["count"])

    async def sum(self, table, field, filters=None, group_by=None):
        t = codec.table_def(table)
        body = {"action": "sum", "filters": codec.encode_filter(t, filters)}
        if field:
            body["field"] = field
        if group_by:
            body["group_by"] = group_by
        return (await self._ok(t, body, write=False))["data"]

    async def ledger_summary(self, filters=None):
        t = codec.table_def("financial_ledger")
        res = await self._ok(t, {"action": "ledger_summary", "filters": codec.encode_filter(t, filters)}, write=False)
        from decimal import Decimal

        return {k: Decimal(v) for k, v in res["data"].items()}

    # ---------------------------------------------------------------- writes --

    async def create(self, table, data):
        t = codec.table_def(table)
        enc = await self._spill(t, codec.encode_doc(t, data))
        res = await self._ok(t, {"action": "create", "data": enc}, write=True)
        return codec.decode_doc(t, res["data"])

    async def batch_create(self, table, rows):
        t = codec.table_def(table)
        out: list[dict] = []
        for off in range(0, len(rows), 500):
            chunk = [await self._spill(t, codec.encode_doc(t, r)) for r in rows[off:off + 500]]
            res = await self._ok(t, {"action": "create", "rows": chunk}, write=True)
            out.extend(codec.decode_doc(t, d) for d in res["data"])
        return out

    async def update(self, table, id, update, filters=None, many=False):
        t = codec.table_def(table)
        upd = codec.encode_update(t, update)
        if "$set" in upd:
            upd["$set"] = (await self._spill(t, upd["$set"]))
        body: dict[str, Any] = {"action": "update", "update": upd, "many": bool(many)}
        if id is not None:
            body["id"] = str(id)
        if filters:
            body["filters"] = codec.encode_filter(t, filters)
        res = await self._ok(t, body, write=True)
        return {"matched": res["data"]["matched"], "modified": res["data"]["modified"],
                "data": codec.decode_doc(t, res["data"].get("data"))}

    async def batch_update(self, table, updates):
        modified = 0
        for filters, update in updates:
            modified += (await self.update(table, None, update, filters=filters))["modified"]
        return modified

    async def find_one_and_update(self, table, filters, update, upsert=False, return_after=True, sort=None):
        t = codec.table_def(table)
        upd = codec.encode_update(t, update)
        if "$set" in upd:
            upd["$set"] = await self._spill(t, upd["$set"])
        body = {"action": "find_one_and_update", "filters": codec.encode_filter(t, filters), "update": upd,
                "upsert": bool(upsert), "return_document": "after" if return_after else "before"}
        if sort:
            body["sort"] = codec.encode_sort(sort)
        res = await self._ok(t, body, write=True)
        return codec.decode_doc(t, res["data"])

    async def delete(self, table, id=None, filters=None, many=False):
        t = codec.table_def(table)
        body: dict[str, Any] = {"action": "delete", "many": bool(many)}
        if id is not None:
            body["id"] = str(id)
        if filters:
            body["filters"] = codec.encode_filter(t, filters)
        res = await self._ok(t, body, write=True)
        return int(res["data"]["deleted"])


def _encode_with_refs(t: dict, doc: dict) -> dict:
    """Like codec.encode_doc but leaves "$var.path" references for the server to resolve."""
    out = {}
    for k, v in doc.items():
        if isinstance(v, str) and v.startswith("$") and len(v) > 1:
            out[k] = v
        else:
            out[k] = codec.encode_field(t, k, v)
    return out


def _decode_op_result(op: dict, t: dict, r: Any) -> Any:
    if r is None or not isinstance(r, (dict, list)):
        return r
    if isinstance(r, dict) and r.get("skipped"):
        return None
    kind = op["op"]
    if kind in ("create", "find_one_and_update") and isinstance(r, dict):
        return codec.decode_doc(t, r)
    if kind == "create" and isinstance(r, list):
        return [codec.decode_doc(t, x) for x in r]
    return r
