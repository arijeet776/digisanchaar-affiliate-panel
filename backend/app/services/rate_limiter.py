"""
Minimal in-memory rate limiting for sensitive endpoints (spec §50): login,
OTP send/verify, password reset, invite creation.

LIMITATION (documented, not silently accepted as fine forever): this is a
single-process in-memory counter. It works correctly for one backend
instance, which matches Part 1/2's scope, but does NOT coordinate across
multiple instances behind a load balancer. Production deployment with more
than one instance needs a shared store (Redis is the natural choice) behind
the same `check()` interface — swapping the backend is a one-file change
because every call site only depends on `check()`, not on how counting
happens.
"""
import time
from collections import defaultdict

from app.core.exceptions import AppError
from fastapi import status


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"


_buckets: dict[str, list[float]] = defaultdict(list)


def check(key: str, limit: int, window_seconds: int) -> None:
    """Raises RateLimitError if `key` has been checked `limit` times within `window_seconds`."""
    now = time.monotonic()
    bucket = _buckets[key]
    cutoff = now - window_seconds
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)

    if len(bucket) >= limit:
        raise RateLimitError("Too many requests. Please try again later.")

    bucket.append(now)


def reset_all() -> None:
    """Test-only helper."""
    _buckets.clear()
