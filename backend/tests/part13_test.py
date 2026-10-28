"""
Part 13 test suite — session/token revocation hardening. Run with:
    python3 tests/part13_test.py

MongoDB-only (mongomock double); no external services needed.
Verifies that an access token is bound to a live refresh session (`sid`), so
logout / admin revoke / revoke-all / self logout-all / rotation / expiry take
effect immediately, and that role/status continue to come from the database.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-for-prod")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("ENVIRONMENT", "development")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, condition, detail=""):
    status_ = "PASS" if condition else "FAIL"
    results.append((name, status_, detail))
    print(f"[{status_}] {name}" + (f" — {detail}" if detail else ""))
    return condition


async def main():
    from mongomock_motor import AsyncMongoMockClient
    import app.db.mongodb as mongodb_module

    mock_client = AsyncMongoMockClient()
    mongodb_module._client = mock_client
    mongodb_module._db = mock_client["quantix_test_part13"]
    await mongodb_module.ensure_indexes(mongodb_module._db)

    from httpx import AsyncClient, ASGITransport
    from app.main import create_app
    from app.core.security import create_access_token, decode_token
    from app.db import session_repository

    app = create_app()
    db = mongodb_module._db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async def issue(email, role):
            r = await client.post("/api/v1/auth/_dev/issue-token", params={"email": email, "role": role})
            j = r.json()
            sub = decode_token(j["access_token"], "access")["sub"]
            return j["access_token"], j["refresh_token"], sub

        def H(tok):
            return {"Authorization": f"Bearer {tok}"}

        sa_tok, _sa_ref, sa_id = await issue("sa13@example.com", "super_admin")
        pub_tok, pub_ref, pub_id = await issue("pub13@example.com", "publisher")

        # ---- A. valid session ----
        claims = decode_token(pub_tok, "access")
        check("Access token carries a session id (sid)", bool(claims.get("sid")))
        r = await client.get("/api/v1/auth/me", headers=H(pub_tok))
        check("Valid session -> 200", r.status_code == 200 and r.json()["role"] == "publisher", r.text)

        # ---- B. tokens that are not bound to a session are refused ----
        legacy = create_access_token(pub_id, "publisher")  # no sid
        r = await client.get("/api/v1/auth/me", headers=H(legacy))
        check("Access token without sid -> 401", r.status_code == 401, r.text)

        forged_admin = create_access_token(pub_id, "super_admin", sid=claims["sid"])
        r = await client.get("/api/v1/admin/security/overview", headers=H(forged_admin))
        check("Forged role claim on a valid session never grants admin (role comes from DB)", r.status_code == 403, r.text)

        other_tok, _o_ref, other_id = await issue("other13@example.com", "publisher")
        cross = create_access_token(pub_id, "publisher", sid=decode_token(other_tok, "access")["sid"])
        r = await client.get("/api/v1/auth/me", headers=H(cross))
        check("sid belonging to a different user -> 401", r.status_code == 401, r.text)

        nonexistent = create_access_token(pub_id, "publisher", sid="no-such-session")
        r = await client.get("/api/v1/auth/me", headers=H(nonexistent))
        check("Unknown sid -> 401", r.status_code == 401, r.text)

        # ---- C. logout revokes the relevant session immediately ----
        tokA, refA, _ = await issue("pub13@example.com", "publisher")
        tokB, refB, _ = await issue("pub13@example.com", "publisher")
        r = await client.post("/api/v1/auth/logout", json={"refresh_token": refA})
        check("Logout -> 200", r.status_code == 200, r.text)
        r = await client.get("/api/v1/auth/me", headers=H(tokA))
        check("Access token of a logged-out session -> 401 (not valid until expiry)", r.status_code == 401, r.text)
        r = await client.get("/api/v1/auth/me", headers=H(tokB))
        check("Other sessions of the same user are unaffected by a single logout", r.status_code == 200, r.text)

        # ---- D. refresh rotation retires the old access token ----
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refB})
        check("Refresh -> 200", r.status_code == 200, r.text)
        new_access = r.json()["access_token"]
        r_old = await client.get("/api/v1/auth/me", headers=H(tokB))
        check("Old access token dies once its session is rotated", r_old.status_code == 401, r_old.text)
        r_new = await client.get("/api/v1/auth/me", headers=H(new_access))
        check("New access token (new session) works", r_new.status_code == 200, r_new.text)
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refB})
        check("Replaying a spent refresh token -> 401", r.status_code == 401, r.text)

        # ---- E. admin revoke of one session ----
        sess = (await client.get(f"/api/v1/admin/security/users/{pub_id}/sessions", headers=H(sa_tok))).json()
        live = [s for s in sess if s["is_live"]]
        check("Admin sees live sessions for the user", len(live) >= 1, sess)
        victim_sid = decode_token(new_access, "access")["sid"]
        r = await client.post(f"/api/v1/admin/security/sessions/{victim_sid}/revoke", headers=H(sa_tok))
        check("Admin revoke -> 200", r.status_code == 200 and r.json()["revoked"] is True, r.text)
        r = await client.get("/api/v1/auth/me", headers=H(new_access))
        check("Admin-revoked session's access token -> 401 immediately", r.status_code == 401, r.text)
        r = await client.get("/api/v1/auth/me", headers=H(sa_tok))
        check("Admin's own session unaffected", r.status_code == 200, r.text)

        # ---- F. admin revoke-all ----
        t1, _r1, _ = await issue("pub13@example.com", "publisher")
        t2, _r2, _ = await issue("pub13@example.com", "publisher")
        r = await client.post(f"/api/v1/admin/security/users/{pub_id}/sessions/revoke-all", headers=H(sa_tok))
        check("Admin revoke-all -> 200", r.status_code == 200, r.text)
        codes = [(await client.get("/api/v1/auth/me", headers=H(t))).status_code for t in (t1, t2)]
        check("Revoke-all invalidates every active access token of that user", codes == [401, 401], codes)
        r = await client.get("/api/v1/auth/me", headers=H(sa_tok))
        check("Revoke-all on one user leaves other users' sessions alone", r.status_code == 200, r.text)

        # ---- G. self logout-all ----
        s1, _x1, uid = await issue("self13@example.com", "manager")
        s2, _x2, _ = await issue("self13@example.com", "manager")
        r = await client.post("/api/v1/auth/logout-all", headers=H(s1))
        check("logout-all -> 200 and reports revoked count", r.status_code == 200 and r.json()["revoked"] >= 2, r.text)
        codes = [(await client.get("/api/v1/auth/me", headers=H(t))).status_code for t in (s1, s2)]
        check("logout-all invalidates all of the caller's tokens", codes == [401, 401], codes)
        r = await client.post("/api/v1/auth/logout-all")
        check("logout-all unauthenticated -> 401", r.status_code == 401)

        # ---- H. expired session ----
        e_tok, _e_ref, e_id = await issue("exp13@example.com", "publisher")
        e_sid = decode_token(e_tok, "access")["sid"]
        await db["refresh_sessions"].update_one({"jti": e_sid}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=5)}})
        r = await client.get("/api/v1/auth/me", headers=H(e_tok))
        check("Expired session -> 401", r.status_code == 401, r.text)

        # ---- I. role / status changes after token issuance (DB-authoritative) ----
        m_tok, _m_ref, m_id = await issue("rolechg13@example.com", "manager")
        r = await client.get("/api/v1/auth/me", headers=H(m_tok))
        check("Manager token: role=manager", r.json().get("role") == "manager", r.text)
        from bson import ObjectId
        await db["users"].update_one({"_id": ObjectId(m_id)}, {"$set": {"role": "publisher"}})
        r = await client.get("/api/v1/auth/me", headers=H(m_tok))
        check("Role demoted after issuance -> /me reports the NEW role", r.status_code == 200 and r.json()["role"] == "publisher", r.text)
        r = await client.get("/api/v1/admin/security/overview", headers=H(m_tok))
        check("Demoted user cannot use old privileges with the old token", r.status_code == 403, r.text)
        await db["users"].update_one({"_id": ObjectId(m_id)}, {"$set": {"account_status": "deactivated"}})
        r = await client.get("/api/v1/auth/me", headers=H(m_tok))
        check("Deactivated after issuance -> 403", r.status_code == 403, r.text)

        # ---- J. unauthorized access after revocation (RBAC endpoints) ----
        p_tok, p_ref, p_id = await issue("rbac13@example.com", "publisher")
        r = await client.get("/api/v1/wallet/summary", headers=H(p_tok))
        before = r.status_code
        await client.post("/api/v1/auth/logout", json={"refresh_token": p_ref})
        r = await client.get("/api/v1/wallet/summary", headers=H(p_tok))
        check("Protected financial endpoint rejects a revoked session", r.status_code == 401, f"before={before} after={r.status_code}")

    print("\n--- SUMMARY ---")
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILURES:")
        for name, status_, detail in failed:
            print(f"  - {name}: {detail}")
        sys.exit(1)


asyncio.run(main())
