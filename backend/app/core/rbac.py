"""
RBAC foundation, DB-authoritative (Part 1 review fix).

Chain of trust for every protected request:

    JWT  ->  user_id  ->  current users record  ->  role + account_status  ->  RBAC

The JWT proves *identity* only ("this bearer is user X"). It is NOT trusted
for *current* role or account status: a token minted an hour ago for a
manager who was demoted or deactivated five minutes ago must stop working
immediately, not at token expiry. So every request re-reads the users
collection and uses that role/status, not the token's `role` claim.

The `role` claim is still issued into the JWT (useful for the frontend to
render the right UI without a round trip), but it is a convenience hint
only — see `get_current_user` below, which never reads it for authorization.

Backend authorization is the source of truth (Principle 24 in the spec).
Role/status here can ONLY come from the verified token's user id plus a
fresh DB lookup — never from a request path/query param, and never from
the token's own role claim.
"""
import asyncio

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.enums import AccountStatus, Role
from app.core.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser:
    def __init__(self, user_id: str, role: Role, account_status: AccountStatus):
        self.user_id = user_id
        self.role = role
        self.account_status = account_status


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    # Import here (not at module load) to avoid a circular import: user_repository
    # imports app.db.mongodb, and keeping rbac.py free of DB-layer imports at
    # module scope keeps this file usable in contexts where Mongo isn't wired
    # up yet (e.g. pure JWT unit tests).
    from app.db.user_repository import get_user_by_id

    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(credentials.credentials, expected_type="access")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")

    # Session binding: the access token must belong to a live (not revoked,
    # not expired) refresh session of the SAME user. Tokens with no `sid`
    # (pre-hardening or forged-shape tokens) are refused. This is what makes
    # logout / admin revoke / revoke-all / password-reset immediate.
    from app.db import session_repository

    sid = payload.get("sid")
    if not sid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session required")
    # The session and user lookups are independent, so they run concurrently
    # (one storage round trip instead of two). The checks and their order are
    # unchanged: an invalid session is refused first, whatever the user lookup did.
    session_res, user_res = await asyncio.gather(
        session_repository.get_session(sid), get_user_by_id(user_id), return_exceptions=True
    )
    if isinstance(session_res, BaseException):
        raise session_res
    session = session_res
    if not session_repository.is_session_live(session) or session.get("user_id") != user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid")

    # Authoritative lookup — deliberately ignores payload["role"].
    if isinstance(user_res, BaseException):
        raise user_res
    user = user_res
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")

    if user.account_status != AccountStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is {user.account_status.value}",
        )

    return CurrentUser(user_id=user.id, role=user.role, account_status=user.account_status)


def require_role(*allowed_roles: Role):
    """Usage: Depends(require_role(Role.SUPER_ADMIN, Role.MANAGER))"""

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return user

    return dependency
