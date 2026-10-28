"""
JWT issue/verify + password hashing + secure token utilities.

Everything downstream (RBAC, endpoints) trusts ONLY what comes out of
decode_token(). Nothing here ever reads a role or user id from a URL/query
param.

Part 2 additions:
- refresh tokens now carry a `jti` (session id) so a specific refresh
  session can be revoked (logout, deactivation, password reset) without
  needing to store the raw refresh token anywhere.
- generate_secure_token()/hash_token() for invite tokens: these need a
  deterministic hash for DB lookup-by-hash, which bcrypt (salted, one-way,
  non-deterministic per call) cannot provide — sha256 is the right tool
  here, distinct from password/OTP hashing.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.core.exceptions import UnauthorizedError

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def generate_secure_token(n_bytes: int = 32) -> str:
    """For invite tokens (and anything else needing an unguessable, one-time secret)."""
    return secrets.token_urlsafe(n_bytes)


def hash_token(token: str) -> str:
    """Deterministic hash for lookup-by-hash (invite tokens). NOT for passwords/OTPs."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_numeric_otp(length: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def _create_token(
    subject: str, role: str, expires_delta: timedelta, token_type: str, jti: str | None = None,
    sid: str | None = None,
) -> tuple[str, str | None]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if jti is not None:
        payload["jti"] = jti
    if sid is not None:
        payload["sid"] = sid
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, jti


def create_access_token(subject: str, role: str, sid: str | None = None) -> str:
    """`sid` binds the access token to its refresh session (the refresh
    token's jti). get_current_user rejects access tokens whose session has
    been revoked/expired, so logout / revoke / revoke-all / password reset
    take effect immediately instead of at access-token expiry."""
    settings = get_settings()
    token, _ = _create_token(
        subject, role, timedelta(minutes=settings.access_token_expire_minutes), "access", sid=sid
    )
    return token


def create_refresh_token(subject: str, role: str) -> tuple[str, str]:
    """Returns (token, jti) — the caller persists jti as the revocable session id."""
    settings = get_settings()
    jti = str(uuid.uuid4())
    token, _ = _create_token(
        subject, role, timedelta(days=settings.refresh_token_expire_days), "refresh", jti=jti
    )
    return token, jti


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired token") from exc

    if payload.get("type") != expected_type:
        raise UnauthorizedError("Wrong token type")

    return payload
