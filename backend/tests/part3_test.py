"""
Part 3 test suite. Run with: python3 tests/part3_test.py
Same in-memory approach as part2_test.py (mongomock-motor + real HTTP calls
through the FastAPI app).
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


BASE_CAMPAIGN = {
    "name": "Summer Push",
    "advertiser_name": "Acme Corp",
    "advertiser_tracking_url": "https://acme.example/track",
    "logo_url": "https://cdn.example/logo.png",
    "description": "Q3 push campaign",
    "platform": "Direct",
    "postback_platform": "custom",
    "postback_config": {"api_key": "super-secret-value", "endpoint": "https://acme.example/pb"},
    "payout_min": 10,
    "payout_max": 100,
    "daily_cap": 1000,
    "overall_cap": None,
    "events": [
        {"event_name": "Install", "payout": 0, "completion_source": "online"},
        {"event_name": "KYC", "payout": 50, "completion_source": "online"},
    ],
}


async def main():
    from mongomock_motor import AsyncMongoMockClient
    import app.db.mongodb as mongodb_module

    mock_client = AsyncMongoMockClient()
    mongodb_module._client = mock_client
    mongodb_module._db = mock_client["quantix_test"]
    await mongodb_module.ensure_indexes(mongodb_module._db)
    check("ensure_indexes runs cleanly (incl. new Part 3 campaign collections)", True)

    from httpx import AsyncClient, ASGITransport
    from app.main import create_app
    from app.services import rate_limiter

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:

        # =========================================================
        # PART 1 + PART 2 REGRESSION (spot checks; full suites run separately)
        # =========================================================
        live = await client.get("/api/v1/health/live")
        check("[regression] /health/live 200", live.status_code == 200)

        sa_tok = (await client.post("/api/v1/auth/_dev/issue-token",
                                     params={"email": "superadmin@example.com", "role": "super_admin"})).json()
        sa_headers = {"Authorization": f"Bearer {sa_tok['access_token']}"}
        mgr_tok = (await client.post("/api/v1/auth/_dev/issue-token",
                                      params={"email": "manager1@example.com", "role": "manager"})).json()
        mgr_headers = {"Authorization": f"Bearer {mgr_tok['access_token']}"}
        pub_tok = (await client.post("/api/v1/auth/_dev/issue-token",
                                      params={"email": "publisher1@example.com", "role": "publisher"})).json()
        pub_headers = {"Authorization": f"Bearer {pub_tok['access_token']}"}

        # =========================================================
        # A. SUPER ADMIN AUTHORIZATION / B. NON-SUPER-ADMIN REJECTION
        # =========================================================
        no_auth = await client.get("/api/v1/admin/campaigns")
        check("Unauthenticated -> 401 on campaigns list", no_auth.status_code == 401)

        mgr_campaigns = await client.get("/api/v1/admin/campaigns", headers=mgr_headers)
        check("Manager denied on campaigns list (403)", mgr_campaigns.status_code == 403)

        pub_campaigns = await client.get("/api/v1/admin/campaigns", headers=pub_headers)
        check("Publisher denied on campaigns list (403)", pub_campaigns.status_code == 403)

        pub_dashboard = await client.get("/api/v1/admin/dashboard", headers=pub_headers)
        check("Publisher denied on dashboard (403)", pub_dashboard.status_code == 403)

        mgr_audit = await client.get("/api/v1/admin/audit-logs", headers=mgr_headers)
        check("Manager denied on audit logs (403)", mgr_audit.status_code == 403)

        sa_dashboard = await client.get("/api/v1/admin/dashboard", headers=sa_headers)
        check("Super Admin allowed on dashboard (200)", sa_dashboard.status_code == 200, sa_dashboard.text)

        # =========================================================
        # H. CAMPAIGN CRUD FOUNDATION
        # =========================================================
        create_resp = await client.post("/api/v1/admin/campaigns", headers=sa_headers, json=BASE_CAMPAIGN)
        check("Campaign creation succeeds", create_resp.status_code == 200, create_resp.text)
        campaign = create_resp.json()
        campaign_id = campaign["campaign_id"]
        check("Campaign starts in DRAFT", campaign["status"] == "draft")
        check("Campaign gets a business campaign_id (not a Mongo _id)", campaign_id.startswith("CAMP") and len(campaign_id) == 8, campaign_id)
        check("Config version starts at 1", campaign["config_version"] == 1)
        check(
            "Sensitive-looking postback_config field masked in response (L: sensitive field exclusion)",
            campaign["config"]["postback_config"]["api_key"] == "***",
            campaign["config"]["postback_config"],
        )
        check("Non-sensitive postback_config field NOT masked", campaign["config"]["postback_config"]["endpoint"] == "https://acme.example/pb")
        check("₹0 event payout accepted as valid", any(e["payout"] == 0 for e in campaign["config"]["events"]))

        get_resp = await client.get(f"/api/v1/admin/campaigns/{campaign_id}", headers=sa_headers)
        check("Campaign detail fetch works", get_resp.status_code == 200 and get_resp.json()["campaign_id"] == campaign_id)

        missing_resp = await client.get("/api/v1/admin/campaigns/CAMPZZZZ", headers=sa_headers)
        check("Nonexistent campaign -> 404", missing_resp.status_code == 404)

        mgr_create_attempt = await client.post("/api/v1/admin/campaigns", headers=mgr_headers, json=BASE_CAMPAIGN)
        check("Manager cannot create campaigns (403)", mgr_create_attempt.status_code == 403)

        invalid_payout = dict(BASE_CAMPAIGN)
        invalid_payout["payout_min"] = 100
        invalid_payout["payout_max"] = 10
        invalid_resp = await client.post("/api/v1/admin/campaigns", headers=sa_headers, json=invalid_payout)
        check("payout_max < payout_min rejected (422)", invalid_resp.status_code == 422, invalid_resp.text)

        empty_name = dict(BASE_CAMPAIGN)
        empty_name["name"] = "   "
        empty_name_resp = await client.post("/api/v1/admin/campaigns", headers=sa_headers, json=empty_name)
        check("Empty campaign name rejected (422)", empty_name_resp.status_code == 422)

        # =========================================================
        # I. CAMPAIGN LIFECYCLE
        # =========================================================
        pause_before_active = await client.post(f"/api/v1/admin/campaigns/{campaign_id}/pause", headers=sa_headers, json={"reason": "test"})
        check("Cannot pause a DRAFT campaign (409 — invalid transition)", pause_before_active.status_code == 409, pause_before_active.text)

        activate_resp = await client.post(f"/api/v1/admin/campaigns/{campaign_id}/activate", headers=sa_headers)
        check("Activate DRAFT -> ACTIVE", activate_resp.status_code == 200 and activate_resp.json()["status"] == "active")

        activate_again = await client.post(f"/api/v1/admin/campaigns/{campaign_id}/activate", headers=sa_headers)
        check("Duplicate activate -> 409 ALREADY_PROCESSED-style conflict", activate_again.status_code == 409)

        pause_no_reason = await client.post(f"/api/v1/admin/campaigns/{campaign_id}/pause", headers=sa_headers, json={"reason": "  "})
        check("Pause with blank reason rejected (422)", pause_no_reason.status_code == 422)

        pause_resp = await client.post(f"/api/v1/admin/campaigns/{campaign_id}/pause", headers=sa_headers, json={"reason": "Advertiser requested hold"})
        check("Pause ACTIVE -> PAUSED with reason", pause_resp.status_code == 200 and pause_resp.json()["status"] == "paused")
        check("Pause reason stored", pause_resp.json()["status_reason"] == "Advertiser requested hold")
        check("Pause reason_type is MANUAL (distinguishable from cap-triggered)", pause_resp.json()["status_reason_type"] == "manual")

        resume_resp = await client.post(f"/api/v1/admin/campaigns/{campaign_id}/resume", headers=sa_headers)
        check("Resume PAUSED -> ACTIVE", resume_resp.status_code == 200 and resume_resp.json()["status"] == "active")

        end_resp = await client.post(f"/api/v1/admin/campaigns/{campaign_id}/end", headers=sa_headers)
        check("End ACTIVE -> ENDED", end_resp.status_code == 200 and end_resp.json()["status"] == "ended")

        end_again = await client.post(f"/api/v1/admin/campaigns/{campaign_id}/end", headers=sa_headers)
        check("Cannot end an already-ended campaign (409)", end_again.status_code == 409)

        still_visible = await client.get(f"/api/v1/admin/campaigns/{campaign_id}", headers=sa_headers)
        check("Ended campaign remains visible/queryable (historical data preserved)", still_visible.status_code == 200)

        # =========================================================
        # CAMPAIGN EDIT + EFFECTIVE SCOPE (Future-Only vs Existing+Future)
        # =========================================================
        edit_campaign_setup = await client.post("/api/v1/admin/campaigns", headers=sa_headers, json=BASE_CAMPAIGN)
        edit_campaign_id = edit_campaign_setup.json()["campaign_id"]

        edit_payload = dict(BASE_CAMPAIGN)
        edit_payload["name"] = "Summer Push V2"
        edit_payload["payout_min"] = 20
        edit_payload["apply_scope"] = "future_only"
        edit_future_only = await client.patch(f"/api/v1/admin/campaigns/{edit_campaign_id}", headers=sa_headers, json=edit_payload)
        check("Campaign edit (future_only) succeeds", edit_future_only.status_code == 200, edit_future_only.text)
        check("Edit creates version 2", edit_future_only.json()["config_version"] == 2)
        check("Edited name reflected in current config", edit_future_only.json()["config"]["name"] == "Summer Push V2")

        history_resp = await client.get(f"/api/v1/admin/campaigns/{edit_campaign_id}/history", headers=sa_headers)
        history = history_resp.json()
        check("History shows both versions", len(history) == 2, history)
        check("History is newest-first", history[0]["version"] == 2 and history[1]["version"] == 1)
        check("Version 1 in history still has the ORIGINAL name (immutable, not overwritten)", history[1]["name"] == "Summer Push")
        check("Version 1's apply_scope recorded as future_only (default at creation)", history[1]["apply_scope"] == "future_only")

        edit_payload2 = dict(BASE_CAMPAIGN)
        edit_payload2["name"] = "Summer Push V3"
        edit_payload2["apply_scope"] = "existing_and_future"
        edit_existing_future = await client.patch(f"/api/v1/admin/campaigns/{edit_campaign_id}", headers=sa_headers, json=edit_payload2)
        check("Campaign edit (existing_and_future) succeeds", edit_existing_future.status_code == 200)
        check("Version 3 created", edit_existing_future.json()["config_version"] == 3)

        history_resp2 = await client.get(f"/api/v1/admin/campaigns/{edit_campaign_id}/history", headers=sa_headers)
        history2 = history_resp2.json()
        check("All 3 versions preserved after existing_and_future edit — nothing overwritten", len(history2) == 3)
        check("Version 3's apply_scope recorded as existing_and_future", history2[0]["apply_scope"] == "existing_and_future")
        check(
            "Version 1 and 2 STILL unchanged after the existing_and_future edit (historical immutability)",
            history2[2]["name"] == "Summer Push" and history2[1]["name"] == "Summer Push V2",
        )

        from app.services.campaign_service import count_existing_affected_records
        affected = await count_existing_affected_records(edit_campaign_id)
        check(
            "count_existing_affected_records is honestly 0 (no click/conversion model exists yet — not fabricated)",
            affected == 0,
        )

        mgr_edit_attempt = await client.patch(f"/api/v1/admin/campaigns/{edit_campaign_id}", headers=mgr_headers, json=edit_payload)
        check("Manager cannot edit campaigns (403)", mgr_edit_attempt.status_code == 403)

        edit_missing = await client.patch("/api/v1/admin/campaigns/CAMPZZZZ", headers=sa_headers, json=edit_payload)
        check("Editing a nonexistent campaign -> 404", edit_missing.status_code == 404)

        # =========================================================
        # CAMPAIGN LISTING / PAGINATION / FILTERING (K)
        # =========================================================
        for i in range(5):
            payload = dict(BASE_CAMPAIGN)
            payload["name"] = f"Bulk Campaign {i}"
            payload["platform"] = "BulkPlatform"
            await client.post("/api/v1/admin/campaigns", headers=sa_headers, json=payload)

        list_page1 = await client.get("/api/v1/admin/campaigns", headers=sa_headers, params={"page": 1, "page_size": 3})
        check("Campaign list pagination returns requested page_size", len(list_page1.json()) == 3, len(list_page1.json()))
        check("Campaign list returns X-Total-Count header", "x-total-count" in {k.lower() for k in list_page1.headers.keys()})
        total_count = int(list_page1.headers.get("X-Total-Count", list_page1.headers.get("x-total-count", "0")))
        check("Total count is at least the 7 campaigns created so far", total_count >= 7, total_count)

        filtered = await client.get("/api/v1/admin/campaigns", headers=sa_headers, params={"platform": "BulkPlatform"})
        check("Platform filter works", all(c["platform"] == "BulkPlatform" for c in filtered.json()) and len(filtered.json()) == 5)

        search_resp = await client.get("/api/v1/admin/campaigns", headers=sa_headers, params={"search": "Summer Push V3"})
        check("Search-by-name filter works (matches CURRENT config name, V3 after two edits)", any("Summer Push V3" in c["name"] for c in search_resp.json()), search_resp.json())

        status_filter = await client.get("/api/v1/admin/campaigns", headers=sa_headers, params={"status": "ended"})
        check("Status filter works", all(c["status"] == "ended" for c in status_filter.json()) and len(status_filter.json()) >= 1)

        # =========================================================
        # DASHBOARD — real counts, honest placeholders
        # =========================================================
        dash = (await client.get("/api/v1/admin/dashboard", headers=sa_headers)).json()
        check("Dashboard total_campaigns is real and matches created count", dash["kpis"]["total_campaigns"]["value"] >= 7, dash["kpis"]["total_campaigns"])
        check("Dashboard total_campaigns marked available=true", dash["kpis"]["total_campaigns"]["available"] is True)
        check(
            "Dashboard revenue/clicks explicitly marked unavailable, not fabricated as 0",
            dash["kpis"]["network_revenue"]["available"] is False and dash["kpis"]["network_revenue"]["value"] is None,
            dash["kpis"]["network_revenue"],
        )
        check("Dashboard pending_approvals present", "pending_approvals" in dash)

        # =========================================================
        # AUDIT LOGGING (J)
        # =========================================================
        audit_resp = await client.get("/api/v1/admin/audit-logs", headers=sa_headers, params={"action": "CAMPAIGN_CREATED", "page_size": 100})
        audit_logs = audit_resp.json()
        check("Audit log captured CAMPAIGN_CREATED events", len(audit_logs) >= 7, len(audit_logs))
        check("Audit log entries don't leak secrets", all("api_key" not in str(a) for a in audit_logs))

        pause_audit = await client.get("/api/v1/admin/audit-logs", headers=sa_headers, params={"action": "CAMPAIGN_PAUSED"})
        check("Audit log captured CAMPAIGN_PAUSED with reason", pause_audit.json()[0]["reason"] == "Advertiser requested hold")

        audit_total_header = "x-total-count" in {k.lower() for k in audit_resp.headers.keys()}
        check("Audit log listing paginated (X-Total-Count present)", audit_total_header)

        # =========================================================
        # MANAGER/PUBLISHER MANAGEMENT — pagination + detail (C, E, G)
        # =========================================================
        mgr_profile_setup = (await client.post("/api/v1/invites/manager", headers=sa_headers, json={})).json()
        # (not completing full onboarding here — Part 2 suite already covers that end-to-end;
        # this section focuses on the NEW Part 3 detail/pagination endpoints)

        managers_list = await client.get("/api/v1/admin/managers", headers=sa_headers, params={"page": 1, "page_size": 1})
        check("Manager list respects page_size", len(managers_list.json()) <= 1)
        check("Manager list has X-Total-Count header", "x-total-count" in {k.lower() for k in managers_list.headers.keys()})

        from app.db import manager_repository as mgr_repo
        from app.core.security import decode_token

        mgr_user_id = decode_token(mgr_tok["access_token"], "access")["sub"]
        await mgr_repo.create_manager_profile(mgr_user_id, "Manager One")

        mgr_detail = await client.get(f"/api/v1/admin/managers/{mgr_user_id}", headers=sa_headers)
        check("Manager detail endpoint returns manager_id/display_name", mgr_detail.status_code == 200 and mgr_detail.json()["manager_id"] is not None, mgr_detail.text)

        mgr_detail_by_manager = await client.get(f"/api/v1/admin/managers/{mgr_user_id}", headers=mgr_headers)
        check("Manager cannot use Super-Admin-only manager-detail endpoint (403)", mgr_detail_by_manager.status_code == 403)

        publishers_list = await client.get("/api/v1/publishers", headers=sa_headers, params={"page_size": 5})
        check("Publisher list endpoint responds (Part 2 contract preserved)", publishers_list.status_code == 200)
        check("Publisher list has X-Total-Count header (new in Part 3)", "x-total-count" in {k.lower() for k in publishers_list.headers.keys()})

        # =========================================================
        # SENSITIVE FIELD EXCLUSION (L) — user listing endpoints
        # =========================================================
        managers_body = await client.get("/api/v1/admin/managers", headers=sa_headers)
        check("Manager list never includes password_hash", all("password_hash" not in m for m in managers_body.json()))

        # =========================================================
        # 401/403/404/409/422/429 HANDLING (M)
        # =========================================================
        garbage = await client.get("/api/v1/admin/campaigns", headers={"Authorization": "Bearer garbage"})
        check("Garbage token -> 401", garbage.status_code == 401)
        check("404 verified above (missing campaign)", True)
        check("409 verified above (duplicate activate/end)", True)
        check("422 verified above (invalid payout / blank name / blank reason)", True)

        # =========================================================
        # FRAUD & SECURITY FOUNDATION — blocked IP registry
        # =========================================================
        pub_fraud_attempt = await client.get("/api/v1/admin/fraud/blocked-ips", headers=pub_headers)
        check("Publisher denied on fraud registry (403)", pub_fraud_attempt.status_code == 403)
        mgr_fraud_attempt = await client.get("/api/v1/admin/fraud/blocked-ips", headers=mgr_headers)
        check("Manager denied on fraud registry (403)", mgr_fraud_attempt.status_code == 403)

        create_block = await client.post(
            "/api/v1/admin/fraud/blocked-ips", headers=sa_headers,
            json={"ip_address": "203.0.113.7", "block_reason": "Abnormal click velocity", "detection_source": "manual"},
        )
        check("Super Admin can register a blocked IP", create_block.status_code == 200, create_block.text)
        blocked = create_block.json()
        check("New blocked IP defaults to status=blocked", blocked["status"] == "blocked")
        check("Detection count starts at 1", blocked["detection_count"] == 1)
        blocked_id = blocked["id"]

        # Re-registering the SAME ip bumps the counter rather than duplicating the row.
        create_block_again = await client.post(
            "/api/v1/admin/fraud/blocked-ips", headers=sa_headers,
            json={"ip_address": "203.0.113.7", "block_reason": "Repeat detection", "detection_source": "manual"},
        )
        check("Re-registering the same IP bumps detection_count instead of duplicating", create_block_again.json()["detection_count"] == 2, create_block_again.json())
        check("Re-registering the same IP keeps the same record id", create_block_again.json()["id"] == blocked_id)

        get_block = await client.get(f"/api/v1/admin/fraud/blocked-ips/{blocked_id}", headers=sa_headers)
        check("Blocked IP detail fetch works", get_block.status_code == 200)

        list_blocks = await client.get("/api/v1/admin/fraud/blocked-ips", headers=sa_headers, params={"status": "blocked"})
        check("Blocked IP list filters by status", any(b["id"] == blocked_id for b in list_blocks.json()))

        investigate_resp = await client.post(f"/api/v1/admin/fraud/blocked-ips/{blocked_id}/investigate", headers=sa_headers)
        check("Investigate sets under_investigation=True without changing status", investigate_resp.json()["under_investigation"] is True and investigate_resp.json()["status"] == "blocked")

        keep_resp = await client.post(f"/api/v1/admin/fraud/blocked-ips/{blocked_id}/keep-blocked", headers=sa_headers)
        check("Keep-blocked is a no-op on status (still blocked, audit-only action)", keep_resp.json()["status"] == "blocked")

        close_inv_resp = await client.post(f"/api/v1/admin/fraud/blocked-ips/{blocked_id}/close-investigation", headers=sa_headers)
        check("Closing investigation clears the flag", close_inv_resp.json()["under_investigation"] is False)

        mark_safe_resp = await client.post(f"/api/v1/admin/fraud/blocked-ips/{blocked_id}/mark-safe", headers=sa_headers)
        check("Mark-safe transitions status to safe", mark_safe_resp.json()["status"] == "safe")

        another_block = await client.post(
            "/api/v1/admin/fraud/blocked-ips", headers=sa_headers,
            json={"ip_address": "198.51.100.23", "block_reason": "Known proxy network", "detection_source": "manual"},
        )
        permanent_resp = await client.post(f"/api/v1/admin/fraud/blocked-ips/{another_block.json()['id']}/permanent-block", headers=sa_headers)
        check("Permanent-block transitions status correctly", permanent_resp.json()["status"] == "permanent_block")

        missing_block = await client.get("/api/v1/admin/fraud/blocked-ips/000000000000000000000000", headers=sa_headers)
        check("Nonexistent blocked-IP id -> 404", missing_block.status_code == 404)

        overview_resp = await client.get("/api/v1/admin/fraud/overview", headers=sa_headers)
        overview = overview_resp.json()
        check("Fraud overview reflects real counts", overview["safe"] >= 1 and overview["permanent_block"] >= 1, overview)

        fraud_audit = await client.get("/api/v1/admin/audit-logs", headers=sa_headers, params={"action": "BLOCKED_IP_PERMANENT_BLOCK"})
        check("Permanent block is audited", len(fraud_audit.json()) >= 1)

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
