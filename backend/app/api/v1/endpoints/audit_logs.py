from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response

from app.core.enums import Role
from app.core.rbac import CurrentUser, require_role
from app.db import audit_repository

router = APIRouter()

_super_admin_only = require_role(Role.SUPER_ADMIN)


def _serialize(log: dict) -> dict:
    return {
        "action": log["action"],
        "actor_user_id": log.get("actor_user_id"),
        "target_user_id": log.get("target_user_id"),
        "before": log.get("before"),
        "after": log.get("after"),
        "reason": log.get("reason"),
        "metadata": log.get("metadata", {}),
        "request_id": log.get("request_id"),
        "timestamp": log["timestamp"],
    }


@router.get("")
async def list_audit_logs(
    response: Response,
    action: str | None = None,
    actor_user_id: str | None = None,
    target_user_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(_super_admin_only),
):
    skip = (page - 1) * page_size
    items, total = await audit_repository.list_logs(
        action=action, actor_user_id=actor_user_id, target_user_id=target_user_id,
        date_from=date_from, date_to=date_to, skip=skip, limit=page_size,
    )
    response.headers["X-Total-Count"] = str(total)
    return [_serialize(item) for item in items]
