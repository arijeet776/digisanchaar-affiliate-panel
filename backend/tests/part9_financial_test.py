"""
Part 9 test suite — Financials + Payments. Run with:
    POSTGRES_DSN=postgresql://postgres:<pw>@localhost:5432/quantix_dev python3 tests/part9_financial_test.py

Unlike Mongo (mongomock-motor gives a fast in-memory double), Postgres has
no equivalent in-process mock with real transaction/locking semantics — so
this suite requires an actual reachable Postgres (local dev instance is
fine; this file only cares that POSTGRES_DSN points somewhere real). It
truncates its own tables at startup for a clean, repeatable run.
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
    postgres_dsn = os.environ.get("POSTGRES_DSN")
    if not postgres_dsn or "localhost" not in postgres_dsn and "127.0.0.1" not in postgres_dsn:
        print("SKIPPED: POSTGRES_DSN must point at a real reachable Postgres for this suite.")
        print("Example: POSTGRES_DSN=postgresql://postgres:<pw>@localhost:5432/quantix_dev")
        sys.exit(2)

    from mongomock_motor import AsyncMongoMockClient
    import app.db.mongodb as mongodb_module

    mock_client = AsyncMongoMockClient()
    mongodb_module._client = mock_client
    mongodb_module._db = mock_client["quantix_test_financial"]
    await mongodb_module.ensure_indexes(mongodb_module._db)
    db = mongodb_module._db

    import app.db.postgres as postgres_module

    await postgres_module.connect_to_postgres()
    pg_ready = await postgres_module.ping_postgres()
    check("Real local Postgres reachable for this test run", pg_ready)
    if not pg_ready:
        print("Cannot continue without Postgres.")
        sys.exit(1)

    from app.db.migrations import run_migrations

    applied = await run_migrations()
    check("Migrations run cleanly (idempotent — 0 or more applied is fine)", True, f"applied={applied}")

    pool = postgres_module.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE financial_ledger, withdrawals RESTART IDENTITY")
    check("Test schema truncated for a clean run", True)

    from httpx import AsyncClient, ASGITransport
    from app.main import create_app
    from app.db import manager_repository, publisher_repository
    from app.core.security import decode_token

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async def token(email, role):
            r = await client.post("/api/v1/auth/_dev/issue-token", params={"email": email, "role": role})
            return r.json()["access_token"], decode_token(r.json()["access_token"], "access")["sub"]

        sa_tok, sa_id = await token("superadmin@example.com", "super_admin")
        sa = {"Authorization": f"Bearer {sa_tok}"}
        mgrA_tok, mgrA_id = await token("managerA@example.com", "manager")
        mgrA = {"Authorization": f"Bearer {mgrA_tok}"}
        mgrB_tok, mgrB_id = await token("managerB@example.com", "manager")
        mgrB = {"Authorization": f"Bearer {mgrB_tok}"}
        pub1_tok, pub1_id = await token("pub1@example.com", "publisher")
        pub1 = {"Authorization": f"Bearer {pub1_tok}"}
        pub2_tok, pub2_id = await token("pub2@example.com", "publisher")
        pub2 = {"Authorization": f"Bearer {pub2_tok}"}

        mgrA_profile = await manager_repository.create_manager_profile(mgrA_id, "Manager A")
        mgrB_profile = await manager_repository.create_manager_profile(mgrB_id, "Manager B")
        pub1_profile = await publisher_repository.create_publisher_profile(pub1_id, mgrA_profile["manager_id"], "Publisher One")
        pub2_profile = await publisher_repository.create_publisher_profile(pub2_id, mgrB_profile["manager_id"], "Publisher Two")
        pub1_pid = pub1_profile["publisher_id"]
        pub2_pid = pub2_profile["publisher_id"]

        # =========================================================
        # A. UNAUTHENTICATED / RBAC / ISOLATION
        # =========================================================
        no_auth = await client.get("/api/v1/wallet/summary")
        check("Unauthenticated -> 401 on wallet summary", no_auth.status_code == 401)

        pub1_no_profile_yet = await client.get("/api/v1/wallet/summary", headers=pub1)
        check("Publisher wallet summary works (0 balance, no earnings yet)", pub1_no_profile_yet.status_code == 200, pub1_no_profile_yet.text)
        check("Fresh wallet balance is 0.00", pub1_no_profile_yet.json()["available_balance"] == "0.00")

        # =========================================================
        # B. EARNING CREATION (idempotent, via financial_service directly —
        #    the conversion-engine integration itself is covered by Part 6's
        #    own suite plus the hook wiring verified here)
        # =========================================================
        from app.services import financial_service

        earn1 = await financial_service.create_earning_for_conversion(
            conversion_id="CONV0001", publisher_id=pub1_pid, manager_id=mgrA_profile["manager_id"],
            campaign_id="CAMP0001", payout=150.0, request_id="req-1",
        )
        check("Earning created for a new conversion", earn1 is not None)

        earn1_dup = await financial_service.create_earning_for_conversion(
            conversion_id="CONV0001", publisher_id=pub1_pid, manager_id=mgrA_profile["manager_id"],
            campaign_id="CAMP0001", payout=150.0, request_id="req-1-retry",
        )
        check("Duplicate earning for same conversion_id is a no-op (idempotent)", earn1_dup is None)

        zero_earn = await financial_service.create_earning_for_conversion(
            conversion_id="CONV0002", publisher_id=pub1_pid, manager_id=mgrA_profile["manager_id"],
            campaign_id="CAMP0001", payout=0, request_id="req-2",
        )
        check("₹0 payout still recorded (valid, per spec)", zero_earn is not None)

        wallet1 = await client.get("/api/v1/wallet/summary", headers=pub1)
        check("Wallet balance reflects earning (₹150.00)", wallet1.json()["available_balance"] == "150.00", wallet1.json())

        # Invalid precision test
        try:
            financial_service.to_money(10.999)
            check("Invalid monetary precision rejected", False)
        except Exception:
            check("Invalid monetary precision rejected", True)

        # =========================================================
        # C. PUBLISHER ISOLATION (spec §18: 2,3,4)
        # =========================================================
        pub2_view_pub1_wallet = await client.get(f"/api/v1/admin/financials/wallets/{pub1_pid}", headers=pub2)
        check("Publisher cannot use admin wallet endpoint at all (403 — role-gated)", pub2_view_pub1_wallet.status_code == 403)

        # Publisher's own list endpoints never take a publisher_id param, so
        # cross-publisher access is structurally impossible for /wallet/*;
        # verify earnings/ledger only ever show their own data.
        pub1_earnings = await client.get("/api/v1/wallet/earnings", headers=pub1)
        check("Publisher earnings list shows only their own conversion(s)", all(e.get("conversion_id") in ("CONV0001", "CONV0002") for e in pub1_earnings.json()["items"]))

        # =========================================================
        # D. MANAGER SCOPE (spec §18: 5)
        # =========================================================
        mgrA_view_pub1 = await client.get(f"/api/v1/admin/financials/wallets/{pub1_pid}", headers=mgrA)
        check("Manager A (owns pub1) can view pub1 wallet", mgrA_view_pub1.status_code == 200)
        mgrB_view_pub1 = await client.get(f"/api/v1/admin/financials/wallets/{pub1_pid}", headers=mgrB)
        check("Manager B (does NOT own pub1) is forbidden from pub1 wallet", mgrB_view_pub1.status_code == 403)

        # =========================================================
        # E. WITHDRAWAL SAFETY (spec §12, §18: 6-9)
        # =========================================================
        neg_wd = await client.post("/api/v1/wallet/withdrawals", headers=pub1, json={"amount": -50})
        check("Negative withdrawal rejected", neg_wd.status_code == 422)

        zero_wd = await client.post("/api/v1/wallet/withdrawals", headers=pub1, json={"amount": 0})
        check("Zero withdrawal rejected", zero_wd.status_code == 422)

        below_min_wd = await client.post("/api/v1/wallet/withdrawals", headers=pub1, json={"amount": 50})
        check("Below-minimum (₹100) withdrawal rejected", below_min_wd.status_code == 422, below_min_wd.text)

        above_balance_wd = await client.post("/api/v1/wallet/withdrawals", headers=pub1, json={"amount": 10000})
        check("Above-available-balance withdrawal rejected", above_balance_wd.status_code == 422, above_balance_wd.text)

        good_wd = await client.post("/api/v1/wallet/withdrawals", headers=pub1, json={"amount": 100, "idempotency_key": "idem-1"})
        check("Valid ₹100 withdrawal succeeds", good_wd.status_code == 200, good_wd.text)
        wd_id = good_wd.json()["withdrawal_id"]
        check("Withdrawal starts in 'requested' status", good_wd.json()["status"] == "requested")

        wallet_after_hold = await client.get("/api/v1/wallet/summary", headers=pub1)
        check("Balance reduced by held withdrawal amount (150 - 100 = 50)", wallet_after_hold.json()["available_balance"] == "50.00", wallet_after_hold.json())

        dup_wd = await client.post("/api/v1/wallet/withdrawals", headers=pub1, json={"amount": 100, "idempotency_key": "idem-1"})
        check("Same idempotency_key returns the SAME withdrawal, not a duplicate", dup_wd.json()["withdrawal_id"] == wd_id)

        second_wd_attempt = await client.post("/api/v1/wallet/withdrawals", headers=pub1, json={"amount": 100})
        check("Cannot request a second withdrawal exceeding the now-reduced balance", second_wd_attempt.status_code == 422)

        # =========================================================
        # F. UNAUTHORIZED APPROVAL / REJECTION (spec §18: 5, 22, 23)
        # =========================================================
        mgrB_approve_attempt = await client.post(f"/api/v1/admin/financials/withdrawals/{wd_id}/approve", headers=mgrB)
        check("Manager B cannot approve pub1's withdrawal (403 — not their scope)", mgrB_approve_attempt.status_code == 403)

        pub2_approve_attempt = await client.post(f"/api/v1/admin/financials/withdrawals/{wd_id}/approve", headers=pub2)
        check("Publisher cannot approve any withdrawal (403 — role-gated)", pub2_approve_attempt.status_code == 403)

        mgrA_approve = await client.post(f"/api/v1/admin/financials/withdrawals/{wd_id}/approve", headers=mgrA)
        check("Manager A (owns pub1) can approve", mgrA_approve.status_code == 200, mgrA_approve.text)

        dup_approve = await client.post(f"/api/v1/admin/financials/withdrawals/{wd_id}/approve", headers=mgrA)
        check("Duplicate approval rejected (already approved)", dup_approve.status_code == 422)

        mgrA_mark_paid_attempt = await client.post(f"/api/v1/admin/financials/withdrawals/{wd_id}/mark-paid", headers=mgrA, json={})
        check("Manager cannot mark paid (Super-Admin-only disbursement authority)", mgrA_mark_paid_attempt.status_code == 403)

        sa_mark_paid = await client.post(f"/api/v1/admin/financials/withdrawals/{wd_id}/mark-paid", headers=sa, json={"reference": "UTR123456"})
        check("Super Admin marks paid", sa_mark_paid.status_code == 200 and sa_mark_paid.json()["status"] == "paid", sa_mark_paid.text)

        dup_paid = await client.post(f"/api/v1/admin/financials/withdrawals/{wd_id}/mark-paid", headers=sa, json={})
        check("Duplicate payment rejected (already paid)", dup_paid.status_code == 422)

        # =========================================================
        # G. REJECTION RELEASES HOLD
        # =========================================================
        # Top up balance first — remaining 50 is below the ₹100 minimum,
        # and this section needs to make two more >=100 withdrawal requests.
        await financial_service.create_earning_for_conversion(
            conversion_id="CONV0003", publisher_id=pub1_pid, manager_id=mgrA_profile["manager_id"],
            campaign_id="CAMP0001", payout=500.0, request_id="req-3",
        )
        wd2 = await client.post("/api/v1/wallet/withdrawals", headers=pub1, json={"amount": 150})
        # balance was 50+500=550, now 550-150=400 held
        wd2_id = wd2.json()["withdrawal_id"]
        reject_no_reason = await client.post(f"/api/v1/admin/financials/withdrawals/{wd2_id}/reject", headers=mgrA, json={"reason": "  "})
        check("Rejection without a real reason is rejected (422)", reject_no_reason.status_code == 422)

        reject_resp = await client.post(f"/api/v1/admin/financials/withdrawals/{wd2_id}/reject", headers=mgrA, json={"reason": "Suspicious pattern"})
        check("Valid rejection succeeds", reject_resp.status_code == 200 and reject_resp.json()["status"] == "rejected")

        wallet_after_reject = await client.get("/api/v1/wallet/summary", headers=pub1)
        check("Rejected withdrawal's hold is released back to balance", wallet_after_reject.json()["available_balance"] == "550.00", wallet_after_reject.json())

        # =========================================================
        # H. CANCELLATION (owner-only, only while 'requested')
        # =========================================================
        wd3 = await client.post("/api/v1/wallet/withdrawals", headers=pub1, json={"amount": 120})
        wd3_id = wd3.json()["withdrawal_id"]
        pub2_cancel_attempt = await client.post(f"/api/v1/wallet/withdrawals/{wd3_id}/cancel", headers=pub2)
        check("Publisher 2 cannot cancel Publisher 1's withdrawal", pub2_cancel_attempt.status_code == 422)
        pub1_cancel = await client.post(f"/api/v1/wallet/withdrawals/{wd3_id}/cancel", headers=pub1)
        check("Publisher can cancel their own pending withdrawal", pub1_cancel.status_code == 200 and pub1_cancel.json()["status"] == "cancelled")

        # =========================================================
        # I. CONCURRENCY RACE (spec §12, §18: 13)
        # =========================================================
        wallet_before_race = await client.get("/api/v1/wallet/summary", headers=pub1)
        avail = float(wallet_before_race.json()["available_balance"])
        check("Balance available for race test", avail >= 100, avail)

        results_race = await asyncio.gather(
            client.post("/api/v1/wallet/withdrawals", headers=pub1, json={"amount": avail}),
            client.post("/api/v1/wallet/withdrawals", headers=pub1, json={"amount": avail}),
            return_exceptions=True,
        )
        statuses = [r.status_code if not isinstance(r, Exception) else "EXC" for r in results_race]
        successes = sum(1 for s in statuses if s == 200)
        check(
            "Concurrent same-publisher withdrawal race: exactly ONE of two full-balance requests succeeds",
            successes == 1, statuses,
        )

        # =========================================================
        # J. FORGED IDs / UNAUTHORIZED ADJUSTMENT (spec §18: 14-16, 22)
        # =========================================================
        forged_wallet = await client.get("/api/v1/admin/financials/wallets/FORGED999", headers=sa)
        check("Forged/nonexistent publisher_id wallet query returns a real (empty) balance, not an error/leak", forged_wallet.status_code == 200 and forged_wallet.json()["available_balance"] == "0.00")

        mgrA_adjustment_attempt = await client.post(
            "/api/v1/admin/financials/adjustments", headers=mgrA,
            json={"publisher_id": pub1_pid, "amount": 500, "direction": "credit", "reason": "test"},
        )
        check("Manager cannot create financial adjustments (Super-Admin-only)", mgrA_adjustment_attempt.status_code == 403)

        sa_adjustment = await client.post(
            "/api/v1/admin/financials/adjustments", headers=sa,
            json={"publisher_id": pub1_pid, "amount": 25, "direction": "credit", "reason": "Goodwill credit"},
        )
        check("Super Admin can create a manual adjustment", sa_adjustment.status_code == 200, sa_adjustment.text)

        # =========================================================
        # K. EARNING REVERSAL (immutability — compensating entry, spec §10)
        # =========================================================
        reverse_resp = await client.post(
            "/api/v1/admin/financials/ledger/CONV0001/reverse", headers=sa, json={"reason": "Advertiser chargeback"}
        )
        check("Earning reversal creates a compensating entry", reverse_resp.status_code == 200, reverse_resp.text)
        check("Reversal entry is a debit", reverse_resp.json()["direction"] == "debit")

        dup_reverse = await client.post(
            "/api/v1/admin/financials/ledger/CONV0001/reverse", headers=sa, json={"reason": "retry"}
        )
        check("Duplicate reversal for same conversion is idempotent (rejected as already-reversed)", dup_reverse.status_code == 422)

        original_still_exists = await client.get("/api/v1/admin/financials/ledger", headers=sa, params={"publisher_id": pub1_pid, "page_size": 50})
        earning_rows = [r for r in original_still_exists.json()["items"] if r.get("conversion_id") == "CONV0001"]
        check(
            "Original earning row is UNCHANGED (still present as 'earning', not edited/deleted)",
            any(r["transaction_type"] == "earning" for r in earning_rows) and any(r["transaction_type"] == "earning_reversal" for r in earning_rows),
            earning_rows,
        )

        # =========================================================
        # L. NETWORK / MANAGER OVERVIEW SCOPE
        # =========================================================
        sa_overview = await client.get("/api/v1/admin/financials/overview", headers=sa)
        check("Super Admin network overview works", sa_overview.status_code == 200, sa_overview.text)
        mgrA_overview = await client.get("/api/v1/admin/financials/overview", headers=mgrA)
        check("Manager overview is scoped (not network-wide)", mgrA_overview.status_code == 200 and "manager_id" in mgrA_overview.json())
        pub1_overview_attempt = await client.get("/api/v1/admin/financials/overview", headers=pub1)
        check("Publisher cannot access admin overview at all", pub1_overview_attempt.status_code == 403)

        # =========================================================
        # M. MIGRATIONS / SCHEMA VERIFICATION
        # =========================================================
        async with pool.acquire() as conn:
            tables = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('financial_ledger','withdrawals','schema_migrations')"
            )
            check("All 3 expected tables exist", len({t['tablename'] for t in tables}) == 3, [t['tablename'] for t in tables])

            indexes = await conn.fetch("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename IN ('financial_ledger','withdrawals')")
            check("Expected indexes exist (>= 8)", len(indexes) >= 8, len(indexes))

            constraints = await conn.fetch(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'financial_ledger'::regclass AND contype = 'u'"
            )
            check("Unique constraints on ledger_id/idempotency_key exist", len(constraints) >= 2, [c['conname'] for c in constraints])

    print("\n--- SUMMARY ---")
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILURES:")
        for name, status_, detail in failed:
            print(f"  - {name}: {detail}")
        sys.exit(1)


asyncio.run(main())
