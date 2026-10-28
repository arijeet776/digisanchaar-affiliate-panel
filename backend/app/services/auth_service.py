"""
Login / refresh / logout / password reset orchestration.

Refresh (spec §10, and Part 1 review point 4 "carried forward" into Part 2):
decode -> look up the session by jti -> confirm it's not revoked/expired ->
re-check the user's CURRENT status in the DB -> only then rotate (revoke old
session, issue a new session + token pair). A deactivated user's refresh
token is rejected even though the JWT itself is still cryptographically
valid — the session lookup and the fresh DB status check are what make
that true, not anything about the token's signature or expiry.
"""
from app.core import audit_actions
from app.core.email_utils import normalize_email
from app.core.enums import AccountStatus, OTPPurpose
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db import session_repository, user_repository
from app.db.audit_repository import record as audit_record
from app.db.mongodb import get_database
from app.services import email_service, otp_service


_STATUS_MESSAGES = {
    AccountStatus.PENDING: "Your account is pending Super Admin approval.",
    AccountStatus.REJECTED: "Your account registration has been rejected.",
}


class LoginResult:
    def __init__(self, access_token: str, refresh_token: str, user):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.user = user


async def _issue_session(user_id: str, role: str) -> tuple[str, str]:
    refresh, jti = create_refresh_token(user_id, role)
    await session_repository.create_session(user_id, jti)
    # Access token is bound to this session (sid == refresh jti).
    access = create_access_token(user_id, role, sid=jti)
    return access, refresh


async def login(email: str, password: str) -> LoginResult:
    email = normalize_email(email)
    user = await user_repository.get_user_by_email(email)

    # Same generic failure for "no such user" and "wrong password" — spec §7/§51
    # (avoid confirming account existence to an unauthenticated caller).
    if user is None or not verify_password(password, user.password_hash):
        await audit_record(audit_actions.LOGIN_FAILED, actor_user_id=None, metadata={"email": email})
        raise UnauthorizedError("Invalid email or password")

    if user.account_status != AccountStatus.ACTIVE:
        # Safe to be specific here (spec §7 draws the enumeration line at
        # *unauthenticated* lookups) — the caller has already proven they
        # know the password, so confirming status isn't an enumeration leak.
        await audit_record(audit_actions.LOGIN_FAILED, actor_user_id=user.id, target_user_id=user.id,
                            metadata={"reason": user.account_status.value})
        raise UnauthorizedError(_STATUS_MESSAGES.get(user.account_status, f"Account is {user.account_status.value}"))

    access, refresh = await _issue_session(user.id, user.role.value)
    await audit_record(audit_actions.LOGIN_SUCCESS, actor_user_id=user.id, target_user_id=user.id)
    return LoginResult(access, refresh, user)


async def refresh(refresh_token: str) -> tuple[str, str]:
    payload = decode_token(refresh_token, expected_type="refresh")
    user_id, jti = payload.get("sub"), payload.get("jti")
    if not user_id or not jti:
        raise UnauthorizedError("Malformed refresh token")

    session = await session_repository.get_session(jti)
    if not session_repository.is_session_live(session):
        raise UnauthorizedError("Session is no longer valid")

    user = await user_repository.get_user_by_id(user_id)
    if user is None or user.account_status != AccountStatus.ACTIVE:
        await session_repository.revoke_session(jti)
        await audit_record(audit_actions.REFRESH_DENIED_INACTIVE_USER, actor_user_id=user_id, target_user_id=user_id)
        raise UnauthorizedError("Account is not active")

    # Rotation: the old session is spent the moment it's used to refresh.
    await session_repository.revoke_session(jti)
    return await _issue_session(user.id, user.role.value)


async def logout(refresh_token: str) -> None:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except UnauthorizedError:
        # An already-invalid/expired token has nothing live to revoke —
        # logging out is still a success from the caller's point of view.
        return
    jti = payload.get("jti")
    user_id = payload.get("sub")
    if jti:
        revoked = await session_repository.revoke_session(jti)
        if revoked:
            await audit_record(audit_actions.LOGOUT, actor_user_id=user_id, target_user_id=user_id)


async def request_password_reset(email: str) -> None:
    """
    Always returns None / no exception, regardless of whether the account
    exists — the generic response is constructed by the endpoint, not here
    (spec §16/§51: never reveal account existence from this flow).
    """
    email = normalize_email(email)
    user = await user_repository.get_user_by_email(email)
    if user is None:
        return

    await otp_service.send_otp(user.id, email, OTPPurpose.PASSWORD_RESET)
    await audit_record(audit_actions.PASSWORD_RESET_REQUESTED, actor_user_id=user.id, target_user_id=user.id)


async def reset_password(email: str, otp_code: str, new_password: str) -> None:
    email = normalize_email(email)
    user = await user_repository.get_user_by_email(email)
    if user is None:
        raise UnauthorizedError("Invalid or expired code")

    result = await otp_service.verify_otp(user.id, OTPPurpose.PASSWORD_RESET, otp_code)
    if not result.success:
        raise UnauthorizedError("Invalid or expired code")

    db = get_database()
    from bson import ObjectId
    from datetime import datetime, timezone

    await db["users"].update_one(
        {"_id": ObjectId(user.id)},
        {"$set": {"password_hash": hash_password(new_password), "updated_at": datetime.now(timezone.utc)}},
    )
    # Security policy: a password change invalidates existing sessions (spec §16/§43).
    await session_repository.revoke_all_sessions_for_user(user.id)
    await audit_record(audit_actions.PASSWORD_CHANGED, actor_user_id=user.id, target_user_id=user.id)
