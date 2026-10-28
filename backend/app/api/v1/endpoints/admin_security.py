"""
Part 11 — Security & Operations controls for Super Admin:
- session visibility/revocation for a given user (operational security
  control: force a compromised or offboarded account's sessions dead
  immediately, without waiting for token expiry)
- a small operational overview combining existing signals (audit activity,
  fraud/blocked-IP state, open support tickets) that already exist from
  Parts 3/6/11 rather than inventing new metrics with no backing data.

Manager is deliberately excluded here (spec §7: a Manager does not get
Super Admin's network-wide authority) — this whole router is Super-Admin-only.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from app.core import audit_actions
from app.core.enums import FraudBlockStatus, Role
from app.core.exceptions import NotFoundError
from app.core.rbac import CurrentUser, require_role
from app.db import blocked_ip_repository, session_repository, support_repository, user_repository
from app.db.audit_repository import list_logs, record as audit_record

router = APIRouter()

_super_admin_only = require_role(Role.SUPER_ADMIN)


@router.get("/overview")
async def security_overview(user: CurrentUser = Depends(_super_admin_only)):
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    _, audit_events_24h = await list_logs(date_from=since, skip=0, limit=1)
    _, login_failures_24h = await list_logs(action=audit_actions.LOGIN_FAILED, date_from=since, skip=0, limit=1)
    open_tickets = await support_repository.count_open()
    blocked_ips = await blocked_ip_repository.count_by_status(FraudBlockStatus.BLOCKED)
    under_investigation = await blocked_ip_repository.count_under_investigation()

    return {
        "audit_events_24h": audit_events_24h,
        "login_failures_24h": login_failures_24h,
        "open_support_tickets": open_tickets,
        "blocked_ips": blocked_ips,
        "ips_under_investigation": under_investigation,
    }


@router.get("/users/{user_id}/sessions")
async def list_user_sessions(user_id: str, user: CurrentUser = Depends(_super_admin_only)):
    target = await user_repository.get_user_by_id(user_id)
    if target is None:
        raise NotFoundError("User not found")
    sessions = await session_repository.list_sessions_for_user(user_id)
    now = datetime.now(timezone.utc)
    return [
        {
            "jti": s["jti"],
            "created_at": s["created_at"].isoformat(),
            "expires_at": s["expires_at"].isoformat(),
            "revoked_at": s["revoked_at"].isoformat() if s.get("revoked_at") else None,
            "is_live": session_repository.is_session_live(s),
        }
        for s in sessions
    ]


@router.post("/sessions/{jti}/revoke")
async def revoke_session(jti: str, user: CurrentUser = Depends(_super_admin_only)):
    session = await session_repository.get_session(jti)
    if session is None:
        raise NotFoundError("Session not found")
    revoked = await session_repository.revoke_session(jti)
    await audit_record(
        audit_actions.SESSION_REVOKED_BY_ADMIN,
        actor_user_id=user.user_id,
        target_user_id=session["user_id"],
        metadata={"jti": jti, "already_revoked": not revoked},
    )
    return {"jti": jti, "revoked": True}


@router.post("/users/{user_id}/sessions/revoke-all")
async def revoke_all_sessions(user_id: str, user: CurrentUser = Depends(_super_admin_only)):
    target = await user_repository.get_user_by_id(user_id)
    if target is None:
        raise NotFoundError("User not found")
    count = await session_repository.revoke_all_sessions_for_user(user_id)
    await audit_record(
        audit_actions.ALL_SESSIONS_REVOKED_BY_ADMIN,
        actor_user_id=user.user_id,
        target_user_id=user_id,
        metadata={"sessions_revoked": count},
    )
    return {"user_id": user_id, "sessions_revoked": count}
