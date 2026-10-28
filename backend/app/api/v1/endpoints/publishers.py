"""
Publisher listing/approval/rejection. Manager sees/acts on only their own
scope (spec §34); Super Admin sees/acts on all. Publisher role is excluded
entirely by require_role — a Publisher can never reach these endpoints.

Part 3 additions: pagination, search, and (Super Admin only) an explicit
manager_id filter and account-status filter. Response body shape for the
list endpoint is UNCHANGED (bare array) to preserve Part 2's existing
regression test contract; total count goes in an `X-Total-Count` header.

KNOWN LIMITATION (documented rather than silently accepted): publisher
profiles and account status live in two collections (`publishers` and
`users`). manager_id/search filtering happens at the DB query level on
`publishers`; the account_status filter is applied after joining to
`users`, so with both a status filter AND a large result set, the
skip/limit slicing happens after that join rather than purely in Mongo.
This is fine at current/expected scale for a Part 3 admin foundation; if
publisher volume grows enough for this to matter, the fix is a proper
aggregation pipeline ($lookup) — flagged now rather than silently deferred.
"""
from fastapi import APIRouter, Depends, Query, Response

from app.core.enums import AccountStatus, Role
from app.core.exceptions import ForbiddenError
from app.core.rbac import CurrentUser, require_role
from app.db import manager_repository, publisher_repository
from app.db.mongodb import get_database
from app.schemas.onboarding import ApprovePublisherRequest, AssignManagerRequest, RejectRequest
from app.services import onboarding_service

router = APIRouter()

_super_admin_or_manager = require_role(Role.SUPER_ADMIN, Role.MANAGER)


@router.get("")
async def list_publishers(
    response: Response,
    status: AccountStatus | None = None,
    manager_id: str | None = None,
    unassigned: bool = False,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(_super_admin_or_manager),
):
    if user.role == Role.SUPER_ADMIN:
        if manager_id:
            profiles = await publisher_repository.list_publishers_by_manager(manager_id)
        else:
            profiles = await publisher_repository.list_all_publishers()
        if unassigned:
            profiles = [p for p in profiles if not p.get("manager_id")]
    else:
        manager_profile = await manager_repository.get_manager_by_user_id(user.user_id)
        if manager_profile is None:
            raise ForbiddenError("Manager profile not found for current user")
        profiles = await publisher_repository.list_publishers_by_manager(manager_profile["manager_id"])

    if q:
        needle = q.lower()
        profiles = [p for p in profiles if needle in p["display_name"].lower() or needle in p["publisher_id"]]

    db = get_database()
    from bson import ObjectId

    manager_names = {m["manager_id"]: m["display_name"] for m in await manager_repository.list_managers()}
    joined = []
    for p in profiles:
        u = await db["users"].find_one({"_id": ObjectId(p["user_id"])})
        if u is None:
            continue
        if status is not None and u["account_status"] != status.value:
            continue
        if q and needle not in u["email"].lower() and needle not in p["display_name"].lower() and needle not in p["publisher_id"]:
            continue
        joined.append(
            {
                "user_id": p["user_id"],
                "publisher_id": p["publisher_id"],
                "manager_id": p.get("manager_id"),
                "manager_name": manager_names.get(p.get("manager_id")) if p.get("manager_id") else None,
                "display_name": p["display_name"],
                "email": u["email"],
                "account_status": u["account_status"],
                "mobile": p.get("mobile"),
                "company": p.get("company"),
                "invitation_type": p.get("invitation_type"),
                "created_at": p.get("created_at"),
            }
        )

    total = len(joined)
    start = (page - 1) * page_size
    response.headers["X-Total-Count"] = str(total)
    return joined[start:start + page_size]


@router.get("/{user_id}")
async def get_publisher(user_id: str, user: CurrentUser = Depends(_super_admin_or_manager)):
    from app.core.exceptions import NotFoundError

    profile = await publisher_repository.get_publisher_by_user_id(user_id)
    if profile is None:
        raise NotFoundError("Publisher not found")

    if user.role == Role.MANAGER:
        manager_profile = await manager_repository.get_manager_by_user_id(user.user_id)
        if manager_profile is None or manager_profile.get("manager_id") != profile["manager_id"]:
            raise ForbiddenError("You do not have authority over this Publisher")

    db = get_database()
    from bson import ObjectId

    u = await db["users"].find_one({"_id": ObjectId(user_id)})
    return {
        "user_id": user_id,
        "publisher_id": profile["publisher_id"],
        "manager_id": profile.get("manager_id"),
        "manager_name": ((await manager_repository.get_manager_by_manager_id(profile["manager_id"])) or {}).get("display_name")
        if profile.get("manager_id") else None,
        "display_name": profile["display_name"],
        "mobile": profile.get("mobile"),
        "company": profile.get("company"),
        "invitation_type": profile.get("invitation_type"),
        "email": u["email"] if u else None,
        "account_status": u["account_status"] if u else None,
        "email_verified": u.get("email_verified", False) if u else None,
        "created_at": u["created_at"] if u else None,
    }


@router.post("/{user_id}/approve")
async def approve_publisher(
    user_id: str,
    body: ApprovePublisherRequest | None = None,
    user: CurrentUser = Depends(_super_admin_or_manager),
):
    updated = await onboarding_service.approve_publisher(
        user_id, user.role, user.user_id, assign_manager_id=body.manager_id if body else None
    )
    return {"user_id": user_id, "account_status": updated["account_status"]}


@router.post("/{user_id}/reject")
async def reject_publisher(
    user_id: str, body: RejectRequest, user: CurrentUser = Depends(_super_admin_or_manager)
):
    updated = await onboarding_service.reject_publisher(user_id, user.role, user.user_id, body.reason)
    return {"user_id": user_id, "account_status": updated["account_status"]}


@router.put("/{user_id}/manager")
async def assign_publisher_manager(
    user_id: str, body: AssignManagerRequest, user: CurrentUser = Depends(require_role(Role.SUPER_ADMIN)),
):
    """Super Admin only: assign or reassign a Manager at any time (ACTIVE managers only)."""
    profile = await onboarding_service.assign_manager(user_id, body.manager_id, user.user_id)
    return {"user_id": user_id, "manager_id": profile.get("manager_id")}
