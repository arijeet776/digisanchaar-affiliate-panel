"""
Super-Admin-only manager management (spec §21, §35, §56 — only Super Admin
approves/rejects Managers; a Manager can never approve another Manager).

Part 3 additions to this Part-2 file: pagination (skip/limit at the DB
query level, per spec §29 "must not load the entire database blindly") and
search-by-email (§30). The response body shape for the list endpoint is
UNCHANGED (still a bare array) specifically so Part 2's existing regression
test — which asserts on that shape — keeps passing unmodified; total count
is carried in an `X-Total-Count` header instead of wrapping the body, which
is the smallest change that satisfies real pagination without breaking a
locked contract. A new manager-detail endpoint (§9 "View Manager") is
added, along with an assigned-publishers sub-view.
"""
from fastapi import APIRouter, Depends, Query, Response

from app.core.enums import AccountStatus, Role
from app.core.exceptions import NotFoundError
from app.core.rbac import CurrentUser, require_role
from app.db import manager_repository, publisher_repository
from app.db.mongodb import get_database
from app.schemas.onboarding import RejectRequest
from app.services import onboarding_service

router = APIRouter()

_super_admin_only = require_role(Role.SUPER_ADMIN)


def _serialize_user(u: dict) -> dict:
    return {
        "user_id": str(u["_id"]), "email": u["email"], "account_status": u["account_status"],
        "email_verified": u.get("email_verified", False), "created_at": u["created_at"],
    }


@router.get("")
async def list_managers(
    response: Response,
    status: AccountStatus | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(_super_admin_only),
):
    db = get_database()
    query: dict = {"role": Role.MANAGER.value}
    if status is not None:
        query["account_status"] = status.value
    if q:
        query["email"] = {"$regex": q, "$options": "i"}

    skip = (page - 1) * page_size
    total = await db["users"].count_documents(query)
    users = await db["users"].find(query).skip(skip).limit(page_size).to_list(length=page_size)
    response.headers["X-Total-Count"] = str(total)
    return [_serialize_user(u) for u in users]


@router.get("/assignable")
async def list_assignable_managers(user: CurrentUser = Depends(_super_admin_only)):
    """ACTIVE Managers only (never pending/rejected/suspended/deactivated) -
    feeds the Super Admin 'Assign Manager' dropdown. Declared before
    /{user_id} so it is not captured as a user id."""
    managers = await manager_repository.list_active_managers()
    return [
        {"manager_id": m["manager_id"], "display_name": m["display_name"], "email": m["email"], "mobile": m.get("mobile")}
        for m in managers
    ]


@router.get("/{user_id}")
async def get_manager(user_id: str, user: CurrentUser = Depends(_super_admin_only)):
    db = get_database()
    from bson import ObjectId

    u = await db["users"].find_one({"_id": ObjectId(user_id), "role": Role.MANAGER.value})
    if u is None:
        raise NotFoundError("Manager not found")
    profile = await manager_repository.get_manager_by_user_id(user_id)
    return {
        **_serialize_user(u),
        "manager_id": profile["manager_id"] if profile else None,
        "display_name": profile["display_name"] if profile else None,
        "mobile": profile.get("mobile") if profile else None,
    }


@router.get("/{user_id}/publishers")
async def get_manager_publishers(user_id: str, user: CurrentUser = Depends(_super_admin_only)):
    profile = await manager_repository.get_manager_by_user_id(user_id)
    if profile is None:
        raise NotFoundError("Manager not found")
    publishers = await publisher_repository.list_publishers_by_manager(profile["manager_id"])
    return [
        {"user_id": p["user_id"], "publisher_id": p["publisher_id"], "display_name": p["display_name"]}
        for p in publishers
    ]


@router.post("/{user_id}/approve")
async def approve_manager(user_id: str, user: CurrentUser = Depends(_super_admin_only)):
    updated = await onboarding_service.approve_manager(user_id, user.user_id)
    return {"user_id": user_id, "account_status": updated["account_status"]}


@router.post("/{user_id}/reject")
async def reject_manager(user_id: str, body: RejectRequest, user: CurrentUser = Depends(_super_admin_only)):
    updated = await onboarding_service.reject_manager(user_id, user.user_id, body.reason)
    return {"user_id": user_id, "account_status": updated["account_status"]}
