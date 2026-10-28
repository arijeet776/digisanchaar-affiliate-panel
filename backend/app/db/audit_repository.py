"""
Audit log storage — append-only by convention (nothing in this module
updates or deletes a record). Never store passwords, OTP codes, or raw
invite/refresh tokens in here (spec §44/§69) — callers pass only ids,
status values, and non-secret metadata.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from pymongo.errors import PyMongoError

from app.core.exceptions import ServiceUnavailableError
from app.core.logging_config import request_id_ctx
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

COLLECTION = "audit_logs"


async def record(
    action: str,
    actor_user_id: str | None,
    target_user_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db = get_database()
    doc = {
        "action": action,
        "actor_user_id": actor_user_id,
        "target_user_id": target_user_id,
        "before": before,
        "after": after,
        "reason": reason,
        "metadata": metadata or {},
        "request_id": request_id_ctx.get(),
        "timestamp": datetime.now(timezone.utc),
    }
    try:
        await db[COLLECTION].insert_one(doc)
    except PyMongoError as exc:
        # Audit logging must never be allowed to break the business
        # operation it's describing — log the failure server-side and move
        # on, rather than raising ServiceUnavailableError here.
        logger.error("Failed to write audit log for action=%s: %s", action, exc)


async def list_logs(
    action: str | None = None,
    actor_user_id: str | None = None,
    target_user_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[dict], int]:
    """Part 3 — Super Admin audit log listing (spec §22/§29/§30)."""
    db = get_database()
    query: dict[str, Any] = {}
    if action:
        query["action"] = action
    if actor_user_id:
        query["actor_user_id"] = actor_user_id
    if target_user_id:
        query["target_user_id"] = target_user_id
    if date_from or date_to:
        ts_filter: dict[str, Any] = {}
        if date_from:
            ts_filter["$gte"] = date_from
        if date_to:
            ts_filter["$lte"] = date_to
        query["timestamp"] = ts_filter

    try:
        total = await db[COLLECTION].count_documents(query)
        cursor = db[COLLECTION].find(query).sort("timestamp", -1).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        return items, total
    except PyMongoError as exc:
        raise ServiceUnavailableError("Audit store unavailable") from exc
