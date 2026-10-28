"""
Auth endpoints — Part 2.

Real login/refresh/logout/password-reset now exist and are DB-backed end to
end (see app/services/auth_service.py). The `_dev/*` helpers from Part 1
are kept only for isolated RBAC-mechanism testing; they remain hard-gated
to `development` and excluded from the OpenAPI schema.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.config import Environment, get_settings
from app.core.enums import AccountStatus, Role
from app.core.exceptions import ForbiddenError
from app.core.rate_limit_dependency import rate_limit
from app.core.rbac import CurrentUser, require_role
from app.db import session_repository
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.db.mongodb import get_database
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.services import auth_service

router = APIRouter()


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("login", limit=10, window_seconds=60))])
async def login(body: LoginRequest):
    result = await auth_service.login(body.email, body.password)
    return TokenResponse(access_token=result.access_token, refresh_token=result.refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest):
    access, refresh = await auth_service.refresh(body.refresh_token)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/logout")
async def logout(body: LogoutRequest):
    await auth_service.logout(body.refresh_token)
    return {"message": "Logged out"}


@router.post("/logout-all")
async def logout_all(user: CurrentUser = Depends(require_role(Role.SUPER_ADMIN, Role.MANAGER, Role.PUBLISHER))):
    """Revoke every session of the caller. Their access tokens stop working
    immediately (access tokens are bound to a live session)."""
    count = await session_repository.revoke_all_sessions_for_user(user.user_id)
    return {"revoked": count}


@router.post(
    "/forgot-password",
    dependencies=[Depends(rate_limit("forgot_password", limit=5, window_seconds=60))],
)
async def forgot_password(body: ForgotPasswordRequest):
    await auth_service.request_password_reset(body.email)
    # Same response whether or not the account exists (spec §16/§51).
    return {"message": "If an account with that email exists, a reset code has been sent."}


@router.post(
    "/reset-password",
    dependencies=[Depends(rate_limit("reset_password", limit=5, window_seconds=60))],
)
async def reset_password(body: ResetPasswordRequest):
    await auth_service.reset_password(body.email, body.otp_code, body.new_password)
    return {"message": "Password has been reset. Please log in again."}


_any_role = require_role(Role.SUPER_ADMIN, Role.MANAGER, Role.PUBLISHER)


@router.get("/me")
async def read_current_user(user: CurrentUser = Depends(_any_role)):
    """Any authenticated, active role can hit this — DB-fresh role/status, never the token claim."""
    return {"user_id": user.user_id, "role": user.role.value, "account_status": user.account_status.value}


# --- Development-only helpers (Part 1 carryover, kept for RBAC-mechanism testing) ---


def _require_dev_environment() -> None:
    if get_settings().environment != Environment.DEVELOPMENT:
        raise ForbiddenError("This endpoint is only available in development")


@router.post("/_dev/issue-token", response_model=TokenResponse, include_in_schema=False)
async def dev_issue_token(email: str, role: Role):
    _require_dev_environment()
    db = get_database()
    now = datetime.now(timezone.utc)

    existing = await db["users"].find_one({"email": email})
    if existing is None:
        result = await db["users"].insert_one(
            {
                "email": email,
                "password_hash": hash_password("dev-only-not-a-real-password"),
                "role": role.value,
                "account_status": AccountStatus.ACTIVE.value,
                "email_verified": True,
                "created_at": now,
                "updated_at": now,
            }
        )
        user_id = str(result.inserted_id)
    else:
        user_id = str(existing["_id"])
        await db["users"].update_one(
            {"_id": existing["_id"]},
            {"$set": {"role": role.value, "account_status": AccountStatus.ACTIVE.value, "updated_at": now}},
        )

    # Same session binding as a real login, so dev tokens exercise the
    # production revocation path (they are revocable like any other).
    refresh, jti = create_refresh_token(user_id, role.value)
    await session_repository.create_session(user_id, jti)
    access = create_access_token(user_id, role.value, sid=jti)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/_dev/deactivate", include_in_schema=False)
async def dev_deactivate(email: str):
    _require_dev_environment()
    db = get_database()
    result = await db["users"].update_one(
        {"email": email},
        {"$set": {"account_status": AccountStatus.DEACTIVATED.value, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"matched": result.matched_count}
