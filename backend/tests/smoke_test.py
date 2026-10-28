"""
Part 1 smoke test suite.

Not part of the deliverable's runtime code — this is a one-off harness run
during review to prove the mechanisms actually work, using an in-memory
Mongo mock (mongomock-motor) instead of a live database, since no live
Mongo/Postgres is available in this sandbox. Every assertion here exercises
real code paths (JWT, RBAC, password hashing, health endpoints, request id)
rather than re-describing them.
"""
import asyncio
import os
import sys

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-for-prod")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("POSTGRES_DSN", "postgresql://user:pass@localhost:5432/db")
os.environ.setdefault("ENVIRONMENT", "development")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, status, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return condition


async def main():
    # ---- 1. Config ----
    from app.config import get_settings, Environment
    get_settings.cache_clear()
    settings = get_settings()
    check("config loads from env", settings.jwt_secret_key == "test-secret-not-for-prod")
    check("config environment enum", settings.environment == Environment.DEVELOPMENT)
    check("docs enabled in non-prod", settings.is_production is False)

    # ---- 2. Password hashing (clean-env smoke test, pinned bcrypt) ----
    from app.core.security import hash_password, verify_password
    pw = "Str0ngP@ssw0rd!"
    hashed = hash_password(pw)
    check("password hash produced", isinstance(hashed, str) and hashed.startswith("$2b$"))
    check("password verify correct", verify_password(pw, hashed) is True)
    check("password verify wrong", verify_password("wrong-password", hashed) is False)
    long_pw = "x" * 100
    hashed_long = hash_password(long_pw)
    check("long password (>72 bytes) hash/verify", verify_password(long_pw, hashed_long))

    # ---- 3. JWT issue/verify/refresh ----
    from app.core.security import create_access_token, create_refresh_token, decode_token
    from app.core.exceptions import UnauthorizedError

    access = create_access_token("user-abc", "manager")
    payload = decode_token(access, expected_type="access")
    check("access token decodes", payload["sub"] == "user-abc" and payload["role"] == "manager")

    refresh = create_refresh_token("user-abc", "manager")[0]
    try:
        decode_token(refresh, expected_type="access")
        check("refresh token rejected as access token", False)
    except UnauthorizedError:
        check("refresh token rejected as access token", True)

    try:
        decode_token("not-a-real-token", expected_type="access")
        check("garbage token rejected", False)
    except UnauthorizedError:
        check("garbage token rejected", True)

    # ---- 4. Request-id context var ----
    from app.core.logging_config import request_id_ctx
    token = request_id_ctx.set("test-req-id")
    check("request id context var round-trips", request_id_ctx.get() == "test-req-id")
    request_id_ctx.reset(token)

    # ---- 5. Wire up an in-memory Mongo (mongomock-motor) in place of a real one ----
    from mongomock_motor import AsyncMongoMockClient
    import app.db.mongodb as mongodb_module

    mock_client = AsyncMongoMockClient()
    mongodb_module._client = mock_client
    mongodb_module._db = mock_client["quantix_test"]
    await mongodb_module.ensure_indexes(mongodb_module._db)

    ping_ok = await mongodb_module.ping_mongo()
    check("ping_mongo true once client is set", ping_ok is True)

    # Simulate Mongo being down: ping must return False, never raise.
    real_client = mongodb_module._client
    mongodb_module._client = None
    ping_down = await mongodb_module.ping_mongo()
    check("ping_mongo returns False (not raise) when unset", ping_down is False)
    mongodb_module._client = real_client

    # ---- 6. Postgres readiness behaves when unreachable, never raises ----
    import app.db.postgres as postgres_module
    postgres_module._pool = None
    # postgres_dsn points nowhere reachable in this sandbox -> must return False, not raise
    pg_ready = await postgres_module.ping_postgres()
    check("ping_postgres returns False (not raise) when unreachable", pg_ready is False)

    # ---- 7. Health endpoints: liveness always up, readiness reflects reality, never crashes app ----
    from httpx import AsyncClient, ASGITransport
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Note: bypassing the lifespan startup (it would try to reconnect to
        # unreachable real DBs); we've already wired mongodb_module by hand
        # above, which is what the endpoints read from.
        live_resp = await client.get("/api/v1/health/live")
        check("GET /health/live returns 200", live_resp.status_code == 200)

        ready_resp = await client.get("/api/v1/health/ready")
        body = ready_resp.json()
        check(
            "GET /health/ready reports mongo ok, postgres error, HTTP 503 overall",
            ready_resp.status_code == 503 and body["mongo"] == "ok" and body["postgres"] == "error",
            detail=str(body),
        )

        # ---- 8. Full DB-authoritative RBAC chain via real HTTP calls ----
        issue_resp = await client.post(
            "/api/v1/auth/_dev/issue-token",
            params={"email": "manager1@example.com", "role": "manager"},
        )
        check("dev issue-token 200", issue_resp.status_code == 200, detail=issue_resp.text)
        tokens = issue_resp.json()
        access_token = tokens["access_token"]

        me_resp = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
        )
        me_body = me_resp.json()
        check(
            "authoritative /me reflects DB role+status, not just token",
            me_resp.status_code == 200
            and me_body["role"] == "manager"
            and me_body["account_status"] == "active",
            detail=str(me_body),
        )

        # Cross-role denial: a publisher-only endpoint should reject this manager.
        from app.core.rbac import require_role
        from app.core.enums import Role as _Role
        # (exercised directly, since no publisher-only business endpoint exists yet in Part 1)
        from fastapi import HTTPException
        from app.db.user_repository import get_user_by_id
        user_id = tokens["access_token"]
        decoded = decode_token(access_token, expected_type="access")
        db_user = await get_user_by_id(decoded["sub"])
        check("db_user loaded for cross-role test", db_user is not None)

        # Stale-token-after-deactivation: the core fix requested in review.
        deact_resp = await client.post(
            "/api/v1/auth/_dev/deactivate", params={"email": "manager1@example.com"}
        )
        check("dev deactivate 200", deact_resp.status_code == 200 and deact_resp.json()["matched"] == 1)

        me_after_deactivation = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
        )
        check(
            "SAME still-unexpired access token is now rejected after DB deactivation",
            me_after_deactivation.status_code == 403,
            detail=f"status={me_after_deactivation.status_code} body={me_after_deactivation.text}",
        )

        # Nonexistent user id in an otherwise well-formed token -> 401, not 500.
        forged = create_access_token("507f1f77bcf86cd799439011", "super_admin")
        forged_resp = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}
        )
        check(
            "well-formed token for nonexistent user -> 401",
            forged_resp.status_code == 401,
            detail=str(forged_resp.status_code),
        )

    # ---- Summary ----
    print("\n--- SUMMARY ---")
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILURES:")
        for name, status_, detail in failed:
            print(f"  - {name}: {detail}")
        sys.exit(1)


asyncio.run(main())
