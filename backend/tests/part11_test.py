"""
Part 11 test suite — Security / Operations / Support. Run with:
    python3 tests/part11_test.py

Unlike part9_financial_test.py, this suite touches only MongoDB (support
tickets, sessions, audit logs) — no Postgres dependency — so it runs
against the in-memory mongomock double and needs no external database.
"""
import asyncio
import os
import sys

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
    mongodb_module._db = mock_client["quantix_test_part11"]
    await mongodb_module.ensure_indexes(mongodb_module._db)

    from httpx import AsyncClient, ASGITransport
    from app.main import create_app
    from app.db import manager_repository, publisher_repository, session_repository
    from app.core.security import decode_token

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async def token(email, role):
            r = await client.post("/api/v1/auth/_dev/issue-token", params={"email": email, "role": role})
            return r.json()["access_token"], decode_token(r.json()["access_token"], "access")["sub"]

        sa_tok, sa_id = await token("sa11@example.com", "super_admin")
        sa = {"Authorization": f"Bearer {sa_tok}"}
        mgrA_tok, mgrA_id = await token("mgrA11@example.com", "manager")
        mgrA = {"Authorization": f"Bearer {mgrA_tok}"}
        mgrB_tok, mgrB_id = await token("mgrB11@example.com", "manager")
        mgrB = {"Authorization": f"Bearer {mgrB_tok}"}
        pub1_tok, pub1_id = await token("pub1_11@example.com", "publisher")
        pub1 = {"Authorization": f"Bearer {pub1_tok}"}
        pub2_tok, pub2_id = await token("pub2_11@example.com", "publisher")
        pub2 = {"Authorization": f"Bearer {pub2_tok}"}

        mgrA_profile = await manager_repository.create_manager_profile(mgrA_id, "Manager A")
        mgrB_profile = await manager_repository.create_manager_profile(mgrB_id, "Manager B")
        await publisher_repository.create_publisher_profile(pub1_id, mgrA_profile["manager_id"], "Publisher One")
        await publisher_repository.create_publisher_profile(pub2_id, mgrB_profile["manager_id"], "Publisher Two")

        # =========================================================
        # A. AUTH
        # =========================================================
        no_auth = await client.get("/api/v1/support/tickets")
        check("Unauthenticated -> 401 on ticket list", no_auth.status_code == 401)

        no_auth_sec = await client.get("/api/v1/admin/security/overview")
        check("Unauthenticated -> 401 on security overview", no_auth_sec.status_code == 401)

        # =========================================================
        # B. TICKET CREATION + OWNERSHIP
        # =========================================================
        create1 = await client.post(
            "/api/v1/support/tickets", headers=pub1,
            json={"subject": "Tracking link not redirecting", "category": "tracking", "priority": "high", "message": "Clicks aren't redirecting to the advertiser URL."},
        )
        check("Publisher can create a ticket", create1.status_code == 200, create1.text)
        check("Priority round-trips correctly", create1.json().get("priority") == "high", create1.json())
        ticket1 = create1.json()["ticket_id"]

        create2 = await client.post(
            "/api/v1/support/tickets", headers=pub2,
            json={"subject": "Withdrawal delayed", "category": "payments", "message": "My withdrawal has been pending for days."},
        )
        check("A second (unrelated) publisher can also create a ticket", create2.status_code == 200, create2.text)
        check("Priority defaults to 'normal' when omitted", create2.json().get("priority") == "normal", create2.json())
        ticket2 = create2.json()["ticket_id"]

        bad_category = await client.post(
            "/api/v1/support/tickets", headers=pub1,
            json={"subject": "x", "category": "not-a-real-category", "message": "hello there"},
        )
        check("Invalid category rejected (422)", bad_category.status_code == 422)

        bad_priority = await client.post(
            "/api/v1/support/tickets", headers=pub1,
            json={"subject": "valid subject", "priority": "urgent!!", "message": "hello there"},
        )
        check("Invalid priority rejected (422)", bad_priority.status_code == 422)

        oversized = await client.post(
            "/api/v1/support/tickets", headers=pub1,
            json={"subject": "valid subject", "message": "x" * 5001},
        )
        check("Oversized message (>5000 chars) rejected (422)", oversized.status_code == 422)

        empty_subject = await client.post(
            "/api/v1/support/tickets", headers=pub1,
            json={"subject": "   ", "message": "valid message body"},
        )
        check("Whitespace-only subject rejected (422)", empty_subject.status_code == 422)

        # =========================================================
        # C. RBAC / SCOPE ISOLATION
        # =========================================================
        pub2_sees_ticket1 = await client.get(f"/api/v1/support/tickets/{ticket1}", headers=pub2)
        check("Publisher cannot view another publisher's ticket", pub2_sees_ticket1.status_code == 403)

        mgrB_sees_ticket1 = await client.get(f"/api/v1/support/tickets/{ticket1}", headers=mgrB)
        check("Manager cannot view a ticket outside their scope", mgrB_sees_ticket1.status_code == 403)

        mgrA_sees_ticket1 = await client.get(f"/api/v1/support/tickets/{ticket1}", headers=mgrA)
        check("Manager CAN view a ticket from their own scoped publisher", mgrA_sees_ticket1.status_code == 200, mgrA_sees_ticket1.text)

        sa_sees_ticket1 = await client.get(f"/api/v1/support/tickets/{ticket1}", headers=sa)
        check("Super Admin can view any ticket", sa_sees_ticket1.status_code == 200)

        mgrA_list = await client.get("/api/v1/support/tickets", headers=mgrA)
        mgrA_ids = {t["ticket_id"] for t in mgrA_list.json()["items"]}
        check("Manager's ticket list is scoped (sees own scope's ticket, not the other manager's)", ticket1 in mgrA_ids and ticket2 not in mgrA_ids, mgrA_ids)

        sa_list = await client.get("/api/v1/support/tickets", headers=sa)
        sa_ids = {t["ticket_id"] for t in sa_list.json()["items"]}
        check("Super Admin ticket list is network-wide", ticket1 in sa_ids and ticket2 in sa_ids, sa_ids)

        pub1_list = await client.get("/api/v1/support/tickets", headers=pub1)
        pub1_ids = {t["ticket_id"] for t in pub1_list.json()["items"]}
        check("Publisher's own ticket list contains only their own ticket", pub1_ids == {ticket1}, pub1_ids)

        # =========================================================
        # D. REPLIES
        # =========================================================
        reply = await client.post(f"/api/v1/support/tickets/{ticket1}/reply", headers=mgrA, json={"body": "Looking into this now."})
        check("Scoped Manager can reply", reply.status_code == 200 and len(reply.json()["messages"]) == 2, reply.text)

        reply_forbidden = await client.post(f"/api/v1/support/tickets/{ticket1}/reply", headers=mgrB, json={"body": "trying to butt in"})
        check("Out-of-scope Manager cannot reply", reply_forbidden.status_code == 403)

        empty_reply = await client.post(f"/api/v1/support/tickets/{ticket1}/reply", headers=pub1, json={"body": "   "})
        check("Empty reply body rejected (422)", empty_reply.status_code == 422)

        # =========================================================
        # E. STATUS TRANSITIONS — Publisher can never resolve own ticket
        # =========================================================
        pub_self_resolve = await client.post(f"/api/v1/support/tickets/{ticket1}/status", headers=pub1, json={"status": "resolved"})
        check("Publisher cannot change their own ticket's status", pub_self_resolve.status_code == 403)

        same_status = await client.post(f"/api/v1/support/tickets/{ticket1}/status", headers=mgrA, json={"status": "open"})
        check("Setting the same status again is rejected as a conflict (409)", same_status.status_code == 409, same_status.text)

        skip_to_resolved = await client.post(f"/api/v1/support/tickets/{ticket1}/status", headers=mgrA, json={"status": "resolved"})
        check("Scoped Manager can move ticket straight to resolved", skip_to_resolved.status_code == 200 and skip_to_resolved.json()["status"] == "resolved", skip_to_resolved.text)
        check("resolved_at timestamp is stamped on first resolution", skip_to_resolved.json().get("resolved_at") is not None, skip_to_resolved.json())

        reopen = await client.post(f"/api/v1/support/tickets/{ticket1}/status", headers=mgrA, json={"status": "in_progress"})
        check("A resolved ticket can be reopened to in_progress", reopen.status_code == 200 and reopen.json()["status"] == "in_progress", reopen.text)

        sa_close = await client.post(f"/api/v1/support/tickets/{ticket1}/status", headers=sa, json={"status": "closed"})
        check("Super Admin can close the ticket", sa_close.status_code == 200 and sa_close.json()["status"] == "closed")
        check("closed_at timestamp is stamped on close", sa_close.json().get("closed_at") is not None, sa_close.json())

        reopen_closed = await client.post(f"/api/v1/support/tickets/{ticket1}/status", headers=sa, json={"status": "open"})
        check("A closed ticket is terminal — cannot transition out (409)", reopen_closed.status_code == 409, reopen_closed.text)

        bad_status = await client.post(f"/api/v1/support/tickets/{ticket2}/status", headers=sa, json={"status": "archived"})
        check("Invalid status value rejected (422)", bad_status.status_code == 422)

        not_found = await client.post("/api/v1/support/tickets/TICKET-NOTREAL/status", headers=sa, json={"status": "closed"})
        check("Nonexistent ticket -> 404 on status change", not_found.status_code == 404)

        not_found_reply = await client.post("/api/v1/support/tickets/TICKET-NOTREAL/reply", headers=sa, json={"body": "hi"})
        check("Nonexistent (forged) ticket id -> 404 on reply", not_found_reply.status_code == 404)

        # =========================================================
        # F. ADMIN SECURITY — sessions
        # =========================================================
        # The `_dev/issue-token` shortcut used above mints tokens directly and
        # deliberately does NOT create a refresh_sessions record (unlike the
        # real /auth/login flow, see auth_service.login) — it exists purely
        # for fast RBAC test setup. To exercise session listing/revocation
        # here we seed real session rows the same way login would.
        await session_repository.create_session(pub1_id, "test-jti-pub1-a")
        await session_repository.create_session(pub1_id, "test-jti-pub1-b")
        await session_repository.create_session(pub2_id, "test-jti-pub2-a")

        mgr_forbidden_sessions = await client.get(f"/api/v1/admin/security/users/{pub1_id}/sessions", headers=mgrA)
        check("Manager cannot access session admin endpoints (Super Admin only)", mgr_forbidden_sessions.status_code == 403)

        pub1_sessions = await client.get(f"/api/v1/admin/security/users/{pub1_id}/sessions", headers=sa)
        check("Super Admin can list a user's sessions", pub1_sessions.status_code == 200 and len(pub1_sessions.json()) >= 1, pub1_sessions.text)
        check(
            "Session response never leaks a token/secret field (whitelisted keys only)",
            all(set(s.keys()) == {"jti", "created_at", "expires_at", "revoked_at", "is_live"} for s in pub1_sessions.json()),
            pub1_sessions.json(),
        )

        jti = pub1_sessions.json()[0]["jti"]
        revoke_resp = await client.post(f"/api/v1/admin/security/sessions/{jti}/revoke", headers=sa)
        check("Super Admin can revoke a specific session", revoke_resp.status_code == 200 and revoke_resp.json()["revoked"] is True, revoke_resp.text)

        after_revoke = await client.get(f"/api/v1/admin/security/users/{pub1_id}/sessions", headers=sa)
        revoked_entry = next(s for s in after_revoke.json() if s["jti"] == jti)
        check("Revoked session shows is_live=False afterwards", revoked_entry["is_live"] is False, revoked_entry)

        revoke_all_resp = await client.post(f"/api/v1/admin/security/users/{pub2_id}/sessions/revoke-all", headers=sa)
        check("Super Admin can revoke-all sessions for a user", revoke_all_resp.status_code == 200, revoke_all_resp.text)

        nonexistent_user = await client.get("/api/v1/admin/security/users/does-not-exist/sessions", headers=sa)
        check("Sessions lookup for nonexistent user -> 404", nonexistent_user.status_code == 404)

        # =========================================================
        # G. ADMIN SECURITY — overview
        # =========================================================
        pub_overview_forbidden = await client.get("/api/v1/admin/security/overview", headers=pub1)
        check("Publisher cannot access security overview", pub_overview_forbidden.status_code == 403)

        overview = await client.get("/api/v1/admin/security/overview", headers=sa)
        check(
            "Security overview returns expected shape with real counted data",
            overview.status_code == 200
            and overview.json().get("open_support_tickets") == 1  # ticket2 still open; ticket1 resolved
            and "audit_events_24h" in overview.json()
            and "blocked_ips" in overview.json(),
            overview.json(),
        )

    print("\n--- SUMMARY ---")
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILURES:")
        for name, status_, detail in failed:
            print(f"  - {name}: {detail}")
        sys.exit(1)


asyncio.run(main())
