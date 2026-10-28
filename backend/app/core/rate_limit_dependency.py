"""
FastAPI dependency factory for rate limiting sensitive endpoints (spec §50).

Keys on client IP + action name, deliberately NOT on request-body content
like an email address: keying on attacker-supplied input would let an
attacker exhaust a specific victim's quota (a denial-of-service on that
victim) just by repeatedly submitting their email — the limiter must
throttle the caller, not whoever the caller claims to be acting on.
"""
from fastapi import Request

from app.services import rate_limiter


def rate_limit(action: str, limit: int, window_seconds: int = 60):
    def dependency(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        rate_limiter.check(f"{action}:{client_ip}", limit, window_seconds)

    return dependency
