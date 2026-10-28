"""
Part 2 test suite. Run with: python3 tests/part2_test.py

Uses mongomock-motor (in-memory, Motor-compatible) since no live Mongo is
available in this sandbox — every assertion here exercises real code paths
(services + real HTTP calls through the FastAPI app), not descriptions.
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
    status_ = "PASS" if condition else "FAIL"
    results.append((name, status_, detail))
    print(f"[{status_}] {name}" + (f" — {detail}" if detail else ""))
    return condition


async def get_latest_otp_code(user_id: str, purpose) -> str:
    """No longer used — see EmailCaptureBackend below for how codes are recovered in tests."""
    raise NotImplementedError


async def main():
    from mongomock_motor import AsyncMongoMockClient
    import app.db.mongodb as mongodb_module

    mock_client = AsyncMongoMockClient()
    mongodb_module._client = mock_client
    mongodb_module._db = mock_client["quantix_test"]
    await mongodb_module.ensure_indexes(mongodb_module._db)
    check("ensure_indexes runs cleanly against mock Mongo (incl. new Part 2 collections)", True)

    # Intercept email delivery at the same seam production would use for a
    # real provider adapter (see app/services/email_service.py), instead of
    # trying to recover a code from its bcrypt hash — bcrypt is deliberately
    # slow, so brute-forcing a 6-digit space against it is infeasible by
    # design (that's the point of hashing it), not a test bug to work around
    # any other way.
    import re
    from app.services import email_service

    sent_messages: list[email_service.EmailMessage] = []

    class CaptureBackend(email_service.EmailBackend):
        async def send(self, message: email_service.EmailMessage) -> None:
            sent_messages.append(message)

    email_service._backend = CaptureBackend()

    def latest_code_for(to_email: str) -> str | None:
        for msg in reversed(sent_messages):
            if msg.to == to_email:
                m = re.search(r"code is (\d{6})", msg.body)
                if m:
                    return m.group(1)
        return None

    from httpx import AsyncClient, ASGITransport
    from app.main import create_app
    from app.core.enums import OTPPurpose, Role, AccountStatus
    from app.services import rate_limiter

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:

        # =========================================================
        # PART 1 REGRESSION — must still pass unchanged
        # =========================================================
        from app.core.security import hash_password, verify_password, create_access_token, decode_token
        from app.core.exceptions import UnauthorizedError

        pw_hash = hash_password("Str0ngP@ssw0rd!")
        check("[P1 regression] password hash/verify", verify_password("Str0ngP@ssw0rd!", pw_hash))

        tok = create_access_token("abc", "manager")
        payload = decode_token(tok, expected_type="access")
        check("[P1 regression] access token decode", payload["sub"] == "abc" and payload["role"] == "manager")

        live = await client.get("/api/v1/health/live")
        check("[P1 regression] /health/live 200", live.status_code == 200)

        ready = await client.get("/api/v1/health/ready")
        check(
            "[P1 regression] /health/ready degrades gracefully (mongo ok, postgres error, 503)",
            ready.status_code == 503 and ready.json()["mongo"] == "ok" and ready.json()["postgres"] == "error",
        )

        dev_issue = await client.post(
            "/api/v1/auth/_dev/issue-token", params={"email": "p1regress@example.com", "role": "manager"}
        )
        check("[P1 regression] dev issue-token still works", dev_issue.status_code == 200)
        dev_access = dev_issue.json()["access_token"]
        me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {dev_access}"})
        check(
            "[P1 regression] /me reflects DB role/status, not token claim",
            me.status_code == 200 and me.json()["role"] == "manager",
        )
        deact = await client.post("/api/v1/auth/_dev/deactivate", params={"email": "p1regress@example.com"})
        me_after = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {dev_access}"})
        check(
            "[P1 regression] stale token rejected after deactivation (403)",
            me_after.status_code == 403,
        )

        rate_limiter.reset_all()

        # =========================================================
        # §59 — FULL PUBLISHER ONBOARDING INTEGRATION TEST
        # =========================================================
        # Bootstrap: a super admin and two managers via dev helper (identity
        # only — this is the same mechanism Part 1 used, not new scope).
        sa_tok = (await client.post("/api/v1/auth/_dev/issue-token",
                                     params={"email": "superadmin@example.com", "role": "super_admin"})).json()
        sa_headers = {"Authorization": f"Bearer {sa_tok['access_token']}"}

        mgrA_tok = (await client.post("/api/v1/auth/_dev/issue-token",
                                       params={"email": "managerA@example.com", "role": "manager"})).json()
        mgrA_headers = {"Authorization": f"Bearer {mgrA_tok['access_token']}"}
        mgrB_tok = (await client.post("/api/v1/auth/_dev/issue-token",
                                       params={"email": "managerB@example.com", "role": "manager"})).json()
        mgrB_headers = {"Authorization": f"Bearer {mgrB_tok['access_token']}"}

        # These managers need real manager profiles (manager_id) — created
        # via the real onboarding path in a moment; for A/B here we create
        # profiles directly since dev-issue-token only sets up the identity
        # record, matching "profiles are populated by onboarding" design.
        from app.db import manager_repository
        mgrA_user_id = decode_token(mgrA_tok["access_token"], "access")["sub"]
        mgrB_user_id = decode_token(mgrB_tok["access_token"], "access")["sub"]
        mgrA_profile = await manager_repository.create_manager_profile(mgrA_user_id, "Manager A")
        mgrB_profile = await manager_repository.create_manager_profile(mgrB_user_id, "Manager B")

        # Manager A creates a publisher invite bound to themselves.
        invite_resp = await client.post(
            "/api/v1/invites/publisher", headers=mgrA_headers, json={"target_email": None}
        )
        check("Manager A can create a publisher invite", invite_resp.status_code == 200, invite_resp.text)
        invite_token = invite_resp.json()["invite_token"]
        check(
            "Publisher invite bound to Manager A's own manager_id (not client-suppliable)",
            invite_resp.json()["manager_id"] == mgrA_profile["manager_id"],
        )

        # Publisher signs up with mixed-case/whitespace email — must normalize.
        signup_resp = await client.post(
            "/api/v1/onboarding/publisher",
            json={
                "invite_token": invite_token,
                "email": " Test@Example.COM ",
                "password": "Str0ngP@ssw0rd!",
                "display_name": "Test Publisher",
            },
        )
        check("Publisher signup succeeds", signup_resp.status_code == 200, signup_resp.text)
        check(
            "Email normalized to lowercase/trimmed",
            signup_resp.json()["email"] == "test@example.com",
            signup_resp.json()["email"],
        )
        check("New publisher status is PENDING", signup_resp.json()["account_status"] == "pending")
        pub_user_id = signup_resp.json()["user_id"]

        # Invite is now consumed — reusing it must fail.
        reuse_resp = await client.post(
            "/api/v1/onboarding/publisher",
            json={
                "invite_token": invite_token,
                "email": "another@example.com",
                "password": "Str0ngP@ssw0rd!",
                "display_name": "Someone Else",
            },
        )
        check("Reused invite token rejected", reuse_resp.status_code == 401, reuse_resp.text)

        # Verify OTP (recovered via test-only brute force helper).
        code = latest_code_for("test@example.com")
        check("OTP was created for the new publisher", code is not None)
        bad_verify = await client.post(
            "/api/v1/otp/verify", json={"email": "test@example.com", "purpose": "email_verification", "code": "000000"}
        )
        check(
            "Wrong OTP code rejected without revealing why",
            bad_verify.status_code == 200 and bad_verify.json()["verified"] is False,
        )
        good_verify = await client.post(
            "/api/v1/otp/verify", json={"email": "test@example.com", "purpose": "email_verification", "code": code}
        )
        check("Correct OTP verifies", good_verify.status_code == 200 and good_verify.json()["verified"] is True, good_verify.text)

        replay_verify = await client.post(
            "/api/v1/otp/verify", json={"email": "test@example.com", "purpose": "email_verification", "code": code}
        )
        check(
            "OTP cannot be replayed after successful verification",
            replay_verify.json()["verified"] is False,
        )

        # Manager B must NOT see or be able to approve Manager A's publisher.
        listB = await client.get("/api/v1/publishers", headers=mgrB_headers)
        pub_ids_visible_to_B = [p["user_id"] for p in listB.json()]
        check("Manager B cannot see Manager A's publisher in their own list", pub_user_id not in pub_ids_visible_to_B)

        approveB_attempt = await client.post(f"/api/v1/publishers/{pub_user_id}/approve", headers=mgrB_headers)
        check("Manager B cannot approve Manager A's publisher (403)", approveB_attempt.status_code == 403, approveB_attempt.text)

        # Super Admin CAN see it.
        listSA = await client.get("/api/v1/publishers", headers=sa_headers)
        check("Super Admin can see the publisher", pub_user_id in [p["user_id"] for p in listSA.json()])

        # Manager A approves.
        approveA = await client.post(f"/api/v1/publishers/{pub_user_id}/approve", headers=mgrA_headers)
        check("Manager A approves successfully", approveA.status_code == 200 and approveA.json()["account_status"] == "active", approveA.text)

        from app.db import publisher_repository
        pub_profile = await publisher_repository.get_publisher_by_user_id(pub_user_id)
        check("Exactly one Publisher ID generated", pub_profile is not None and len(pub_profile["publisher_id"]) == 4)

        # Repeat approval — must be idempotent / already-processed, not a second ID or email.
        approveA_again = await client.post(f"/api/v1/publishers/{pub_user_id}/approve", headers=mgrA_headers)
        check(
            "Duplicate approval returns ALREADY_PROCESSED, not a second success",
            approveA_again.status_code == 409, approveA_again.text,
        )
        approveSA_again = await client.post(f"/api/v1/publishers/{pub_user_id}/approve", headers=sa_headers)
        check(
            "Super Admin approving an already-approved publisher also gets ALREADY_PROCESSED (race safety)",
            approveSA_again.status_code == 409,
        )
        pub_profile_after = await publisher_repository.get_publisher_by_user_id(pub_user_id)
        check("Publisher ID unchanged after duplicate approval attempts", pub_profile_after["publisher_id"] == pub_profile["publisher_id"])

        # =========================================================
        # §60 — SUPER ADMIN / MANAGER ONBOARDING INTEGRATION TEST
        # =========================================================
        mgr_invite = await client.post("/api/v1/invites/manager", headers=sa_headers, json={"target_email": None})
        check("Super Admin can create a manager invite", mgr_invite.status_code == 200, mgr_invite.text)
        mgr_invite_token = mgr_invite.json()["invite_token"]

        mgr_invite_by_manager = await client.post("/api/v1/invites/manager", headers=mgrA_headers, json={"target_email": None})
        check("Manager CANNOT create a manager invite (403)", mgr_invite_by_manager.status_code == 403)

        mgr_signup = await client.post(
            "/api/v1/onboarding/manager",
            json={
                "invite_token": mgr_invite_token,
                "email": "newmanager@example.com",
                "password": "Str0ngP@ssw0rd!",
                "display_name": "New Manager",
            },
        )
        check("Manager signup succeeds", mgr_signup.status_code == 200, mgr_signup.text)
        new_mgr_user_id = mgr_signup.json()["user_id"]

        mgr_code = latest_code_for("newmanager@example.com")
        mgr_verify = await client.post(
            "/api/v1/otp/verify", json={"email": "newmanager@example.com", "purpose": "email_verification", "code": mgr_code}
        )
        check("Manager OTP verifies", mgr_verify.json()["verified"] is True)

        list_pending_managers = await client.get("/api/v1/admin/managers", headers=sa_headers, params={"status": "pending"})
        check("Super Admin sees pending manager application", new_mgr_user_id in [m["user_id"] for m in list_pending_managers.json()])

        mgr_approve = await client.post(f"/api/v1/admin/managers/{new_mgr_user_id}/approve", headers=sa_headers)
        check("Super Admin approves manager", mgr_approve.status_code == 200 and mgr_approve.json()["account_status"] == "active")

        new_mgr_profile = await manager_repository.get_manager_by_user_id(new_mgr_user_id)
        check(
            "Unique Manager ID generated, format AM+digits",
            new_mgr_profile is not None and new_mgr_profile["manager_id"].startswith("AM"),
            new_mgr_profile["manager_id"] if new_mgr_profile else None,
        )

        mgr_approve_again = await client.post(f"/api/v1/admin/managers/{new_mgr_user_id}/approve", headers=sa_headers)
        check("Duplicate manager approval -> ALREADY_PROCESSED", mgr_approve_again.status_code == 409)

        # =========================================================
        # §61 — REFRESH SECURITY TEST (real login this time, not dev token)
        # =========================================================
        from app.db.mongodb import get_database
        from bson import ObjectId
        from datetime import datetime, timezone

        db = get_database()
        await db["users"].update_one(
            {"_id": ObjectId(new_mgr_user_id)}, {"$set": {"updated_at": datetime.now(timezone.utc)}}
        )

        login_resp = await client.post(
            "/api/v1/auth/login", json={"email": "newmanager@example.com", "password": "Str0ngP@ssw0rd!"}
        )
        check("Real login succeeds for approved+verified manager", login_resp.status_code == 200, login_resp.text)
        login_tokens = login_resp.json()
        mgr_access = login_tokens["access_token"]
        mgr_refresh = login_tokens["refresh_token"]

        wrong_pw = await client.post(
            "/api/v1/auth/login", json={"email": "newmanager@example.com", "password": "wrong-password"}
        )
        check("Wrong password rejected (401)", wrong_pw.status_code == 401)
        check(
            "Wrong password and nonexistent email give the SAME generic message (no enumeration)",
            wrong_pw.json()["error"]["message"]
            == (await client.post("/api/v1/auth/login", json={"email": "nosuchuser@example.com", "password": "x"})).json()["error"]["message"],
        )

        refresh_before = await client.post("/api/v1/auth/refresh", json={"refresh_token": mgr_refresh})
        check("Refresh works while account is active", refresh_before.status_code == 200, refresh_before.text)
        rotated_refresh = refresh_before.json()["refresh_token"]

        old_refresh_reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": mgr_refresh})
        check("Old (rotated-out) refresh token can no longer be used", old_refresh_reuse.status_code == 401)

        await db["users"].update_one(
            {"_id": ObjectId(new_mgr_user_id)}, {"$set": {"account_status": AccountStatus.DEACTIVATED.value}}
        )
        refresh_after_deactivation = await client.post("/api/v1/auth/refresh", json={"refresh_token": rotated_refresh})
        check(
            "Refresh FAILS after deactivation, even with a still-valid refresh token",
            refresh_after_deactivation.status_code == 401, refresh_after_deactivation.text,
        )

        me_with_old_access = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {mgr_access}"})
        check(
            "Old still-unexpired ACCESS token also rejected after deactivation",
            # Part 13 binds access tokens to a session: 401 (session revoked) or 403 (account inactive).
            me_with_old_access.status_code in (401, 403),
        )

        # restore for later tests
        await db["users"].update_one(
            {"_id": ObjectId(new_mgr_user_id)}, {"$set": {"account_status": AccountStatus.ACTIVE.value}}
        )

        # =========================================================
        # LOGOUT
        # =========================================================
        login2 = (await client.post("/api/v1/auth/login", json={"email": "newmanager@example.com", "password": "Str0ngP@ssw0rd!"})).json()
        logout_resp = await client.post("/api/v1/auth/logout", json={"refresh_token": login2["refresh_token"]})
        check("Logout succeeds", logout_resp.status_code == 200)
        refresh_after_logout = await client.post("/api/v1/auth/refresh", json={"refresh_token": login2["refresh_token"]})
        check("Refresh fails after logout (session revoked)", refresh_after_logout.status_code == 401)

        # =========================================================
        # PASSWORD RESET FLOW
        # =========================================================
        forgot1 = await client.post("/api/v1/auth/forgot-password", json={"email": "newmanager@example.com"})
        forgot2 = await client.post("/api/v1/auth/forgot-password", json={"email": "nosuchuser@example.com"})
        check(
            "forgot-password gives identical generic response for real vs nonexistent email",
            forgot1.status_code == forgot2.status_code == 200 and forgot1.json() == forgot2.json(),
        )

        reset_code = latest_code_for("newmanager@example.com")
        bad_reset = await client.post(
            "/api/v1/auth/reset-password",
            json={"email": "newmanager@example.com", "otp_code": "000000", "new_password": "NewStr0ngP@ss!"},
        )
        check("Wrong reset code rejected", bad_reset.status_code == 401)

        good_reset = await client.post(
            "/api/v1/auth/reset-password",
            json={"email": "newmanager@example.com", "otp_code": reset_code, "new_password": "NewStr0ngP@ss!"},
        )
        check("Password reset with correct code succeeds", good_reset.status_code == 200, good_reset.text)

        old_pw_login = await client.post(
            "/api/v1/auth/login", json={"email": "newmanager@example.com", "password": "Str0ngP@ssw0rd!"}
        )
        check("Old password no longer works after reset", old_pw_login.status_code == 401)
        new_pw_login = await client.post(
            "/api/v1/auth/login", json={"email": "newmanager@example.com", "password": "NewStr0ngP@ss!"}
        )
        check("New password works after reset", new_pw_login.status_code == 200)

        # =========================================================
        # RBAC / ROLE-TAMPERING / SCOPE SECURITY TESTS (spec §58)
        # =========================================================
        pub_login_tok = (await client.post(
            "/api/v1/auth/_dev/issue-token", params={"email": "activepublisher@example.com", "role": "publisher"}
        )).json()
        pub_headers = {"Authorization": f"Bearer {pub_login_tok['access_token']}"}

        pub_hits_admin = await client.get("/api/v1/admin/managers", headers=pub_headers, params={"status": "pending"})
        check("Publisher cannot access Super-Admin-only endpoint (403)", pub_hits_admin.status_code == 403)

        pub_hits_publishers_list = await client.get("/api/v1/publishers", headers=pub_headers)
        check("Publisher cannot access Manager/Admin publisher-list endpoint (403)", pub_hits_publishers_list.status_code == 403)

        pub_creates_invite = await client.post("/api/v1/invites/publisher", headers=pub_headers, json={})
        check("Publisher cannot create invites (403)", pub_creates_invite.status_code == 403)

        no_auth = await client.get("/api/v1/publishers")
        check("Unauthenticated request rejected (401)", no_auth.status_code == 401)

        garbage_token = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"})
        check("Garbage bearer token rejected (401)", garbage_token.status_code == 401)

        # Manager creating a publisher invite: client-supplied manager_id must be ignored, not honored.
        spoofed_invite = await client.post(
            "/api/v1/invites/publisher", headers=mgrB_headers, json={"manager_id": mgrA_profile["manager_id"]}
        )
        check(
            "Manager's own invite is bound to THEIR manager_id even if a different one is supplied",
            spoofed_invite.json()["manager_id"] == mgrB_profile["manager_id"],
            spoofed_invite.json(),
        )

        # Part 16.2.1 (deliberate contract change): a Super Admin publisher invite
        # carries NO manager; the manager is assigned at approval instead.
        sa_invite_no_mgr = await client.post("/api/v1/invites/publisher", headers=sa_headers, json={})
        check("Super Admin publisher-invite without manager_id is allowed and unassigned (Part 16.2.1)",
              sa_invite_no_mgr.status_code == 200 and sa_invite_no_mgr.json()["manager_id"] is None, sa_invite_no_mgr.text)

        # =========================================================
        # INVITE LIFECYCLE: revoke, expiry
        # =========================================================
        revoke_target = await client.post("/api/v1/invites/publisher", headers=mgrA_headers, json={})
        rt_token = revoke_target.json()["invite_token"]
        revoke_by_other = await client.post(f"/api/v1/invites/{rt_token}/revoke", headers=mgrB_headers)
        check("Manager B cannot revoke Manager A's invite (403)", revoke_by_other.status_code == 403)
        revoke_by_owner = await client.post(f"/api/v1/invites/{rt_token}/revoke", headers=mgrA_headers)
        check("Manager A can revoke their own invite", revoke_by_owner.status_code == 200 and revoke_by_owner.json()["revoked"] is True)

        revoked_signup_attempt = await client.post(
            "/api/v1/onboarding/publisher",
            json={"invite_token": rt_token, "email": "shouldfail@example.com", "password": "Str0ngP@ssw0rd!", "display_name": "X"},
        )
        check("Signup with a revoked invite token is rejected", revoked_signup_attempt.status_code == 401)

        # Expired invite (force expiry in DB directly, since real TTL is 72h)
        expiring = await client.post("/api/v1/invites/publisher", headers=mgrA_headers, json={})
        exp_token = expiring.json()["invite_token"]
        from app.core.security import hash_token
        await db["invites"].update_one(
            {"token_hash": hash_token(exp_token)}, {"$set": {"expires_at": datetime.now(timezone.utc)}}
        )
        expired_signup_attempt = await client.post(
            "/api/v1/onboarding/publisher",
            json={"invite_token": exp_token, "email": "alsofail@example.com", "password": "Str0ngP@ssw0rd!", "display_name": "X"},
        )
        check("Signup with an expired invite token is rejected", expired_signup_attempt.status_code == 401)

        # =========================================================
        # OTP SECURITY: brute force / max attempts, resend cooldown
        # =========================================================
        brute_invite = await client.post("/api/v1/invites/publisher", headers=mgrA_headers, json={})
        brute_signup = await client.post(
            "/api/v1/onboarding/publisher",
            json={
                "invite_token": brute_invite.json()["invite_token"],
                "email": "brutetarget@example.com",
                "password": "Str0ngP@ssw0rd!",
                "display_name": "Brute Target",
            },
        )
        brute_user_id = brute_signup.json()["user_id"]

        last_result = None
        for attempt in range(6):
            last_result = await client.post(
                "/api/v1/otp/verify",
                json={"email": "brutetarget@example.com", "purpose": "email_verification", "code": "999999"},
            )
        check(
            "OTP verification locks out after max attempts (still reports invalid, not a distinct error)",
            last_result.json()["verified"] is False,
        )
        from app.db.otp_repository import get_active_otp
        active_after_lockout = await get_active_otp(brute_user_id, OTPPurpose.EMAIL_VERIFICATION)
        check("After max attempts, the OTP is no longer ACTIVE (can't be found/used even with the right code)", active_after_lockout is None)

        # Resend cooldown
        cooldown_invite = await client.post("/api/v1/invites/publisher", headers=mgrA_headers, json={})
        cooldown_signup = await client.post(
            "/api/v1/onboarding/publisher",
            json={
                "invite_token": cooldown_invite.json()["invite_token"],
                "email": "cooldowntarget@example.com",
                "password": "Str0ngP@ssw0rd!",
                "display_name": "Cooldown Target",
            },
        )
        resend_immediately = await client.post(
            "/api/v1/otp/send", json={"email": "cooldowntarget@example.com", "purpose": "email_verification"}
        )
        check(
            "Immediate OTP resend is rate-limited by cooldown (429)",
            resend_immediately.status_code == 429, resend_immediately.text,
        )

        # =========================================================
        # LOGIN FOR NON-ACTIVE STATUSES
        # =========================================================
        pending_login = await client.post(
            "/api/v1/auth/login", json={"email": "cooldowntarget@example.com", "password": "Str0ngP@ssw0rd!"}
        )
        check(
            "Login for a still-PENDING account is rejected with a specific (post-auth-safe) message",
            pending_login.status_code == 401 and "pending" in pending_login.json()["error"]["message"].lower(),
            pending_login.text,
        )

    # =========================================================
    # SUMMARY
    # =========================================================
    print("\n--- SUMMARY ---")
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILURES:")
        for name, status_, detail in failed:
            print(f"  - {name}: {detail}")
        sys.exit(1)


asyncio.run(main())
