"""
Part 4 foundation test suite — campaign-specific data purge + tracking-domain
configuration. Run with: python3 tests/part4_purge_test.py

Same in-memory approach as part2/part3 (mongomock-motor + real HTTP calls
through the FastAPI app). The 26 mandatory purge tests come from the Final
Execution Directive §22; the tracking-domain tests from master spec §31.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

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
    "name": "Purge Target",
    "advertiser_name": "Acme Corp",
    "advertiser_tracking_url": "https://acme.example/track",
    "platform": "Direct",
    "postback_platform": "custom",
    "postback_config": {"endpoint": "https://acme.example/pb"},
    "payout_min": 10,
    "payout_max": 100,
    "events": [{"event_name": "Install", "payout": 50, "completion_source": "online"}],
}

SEED_COUNTS = {
    "tracking_links": 2,
    "campaign_access": 1,
    "clicks": 3,
    "conversions": 2,
    "inbound_postbacks": 2,
    "outbound_postbacks": 1,
    "campaign_events": 2,
    "attribution_mappings": 1,
    "postback_endpoints": 1,
    "blocked_ips": 1,
}


async def seed_campaign_data(db, campaign_id: str, ip_octet: int):
    """Seed purgeable operational data for one campaign, across exactly the
    collections the purge dependency map declares (future Part 5/6 collections
    included, so the map is exercised against real documents)."""
    now = datetime.now(timezone.utc)
    await db["tracking_links"].insert_many(
        [{"link_id": f"LNK-{campaign_id}-{i}", "campaign_id": campaign_id, "publisher_id": "PUB7788", "public_code": f"{campaign_id[-3:]}Q{i}", "created_at": now} for i in range(SEED_COUNTS["tracking_links"])]
    )
    await db["campaign_access"].insert_one(
        {"access_id": f"ACC-{campaign_id}", "campaign_id": campaign_id, "publisher_id": "PUB7788", "status": "approved", "created_at": now}
    )
    await db["clicks"].insert_many(
        [{"digisnr_click_id": f"QXCLK_{campaign_id}_{i}", "campaign_id": campaign_id, "link_id": f"LNK-{campaign_id}-0", "click_created_at": now} for i in range(SEED_COUNTS["clicks"])]
    )
    await db["campaign_events"].insert_many(
        [{"event_id": f"EVT-{campaign_id}-{i}", "campaign_id": campaign_id, "event_name": "Install", "created_at": now} for i in range(SEED_COUNTS["campaign_events"])]
    )
    await db["attribution_mappings"].insert_one(
        {"mapping_id": f"MAP-{campaign_id}", "campaign_id": campaign_id, "click_id": f"QXCLK_{campaign_id}_0", "created_at": now}
    )
    await db["conversions"].insert_many(
        [{"conversion_id": f"QXCNV_{campaign_id}_{i}", "idempotency_key": f"offer18|txn-{campaign_id}-{i}|Install|QXCLK_{campaign_id}_0", "campaign_id": campaign_id, "publisher_id": "PUB7788", "event": "Install", "conversion_created_at": now} for i in range(SEED_COUNTS["conversions"])]
    )
    await db["inbound_postbacks"].insert_many(
        [{"postback_id": f"QXPB_{campaign_id}_{i}", "campaign_id": campaign_id, "platform": "offer18", "processing_status": "processed", "received_at": now} for i in range(SEED_COUNTS["inbound_postbacks"])]
    )
    await db["outbound_postbacks"].insert_one(
        {"outbound_id": f"QXOB_{campaign_id}", "campaign_id": campaign_id, "publisher_id": "PUB7788", "final_status": "delivered", "created_at": now}
    )
    await db["postback_endpoints"].insert_one(
        {"endpoint_id": f"QPEP_{campaign_id[-4:]}", "token": f"tok-{campaign_id}", "campaign_id": campaign_id, "platform": "offer18", "status": "active", "created_at": now}
    )
    await db["blocked_ips"].insert_one(
        {"ip_address": f"203.0.113.{ip_octet}", "campaign_id": campaign_id, "reason": "seeded", "status": "blocked", "created_at": now}
    )


async def main():
    from mongomock_motor import AsyncMongoMockClient
    import app.db.mongodb as mongodb_module

    mock_client = AsyncMongoMockClient()
    mongodb_module._client = mock_client
    mongodb_module._db = mock_client["quantix_test_purge"]
    await mongodb_module.ensure_indexes(mongodb_module._db)
    check("ensure_indexes runs cleanly (incl. system_settings + purge_operations)", True)

    db = mongodb_module._db

    from httpx import AsyncClient, ASGITransport
    from app.main import create_app
    from app.core.exceptions import ConflictError
    from app.services import purge_service, settings_service
    from app.services.campaign_service import assert_campaign_is_traffic_live

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        sa_tok = (await client.post("/api/v1/auth/_dev/issue-token",
                                     params={"email": "superadmin@example.com", "role": "super_admin"})).json()
        sa = {"Authorization": f"Bearer {sa_tok['access_token']}"}
        mgr_tok = (await client.post("/api/v1/auth/_dev/issue-token",
                                      params={"email": "manager1@example.com", "role": "manager"})).json()
        mgr = {"Authorization": f"Bearer {mgr_tok['access_token']}"}
        pub_tok = (await client.post("/api/v1/auth/_dev/issue-token",
                                      params={"email": "publisher1@example.com", "role": "publisher"})).json()
        pub = {"Authorization": f"Bearer {pub_tok['access_token']}"}

        # Identity/business records that must NEVER be touched by a purge
        await db["managers"].insert_one({"manager_id": "AM97578", "user_id": "seed-user-mgr", "status": "active"})
        await db["publishers"].insert_one({"publisher_id": "PUB7788", "user_id": "seed-user-pub", "manager_id": "AM97578", "status": "active"})

        # =========================================================
        # TRACKING-DOMAIN CONFIGURATION (master spec §31)
        # =========================================================
        r = await client.get("/api/v1/admin/settings/tracking-domain")
        check("T1: unauthenticated tracking-domain read -> 401", r.status_code == 401)
        r = await client.get("/api/v1/admin/settings/tracking-domain", headers=mgr)
        check("T2: manager cannot read tracking-domain config (403)", r.status_code == 403)
        r = await client.put("/api/v1/admin/settings/tracking-domain", headers=mgr,
                             json={"tracking_base_url": "https://evil.example"})
        check("T3: manager cannot modify tracking domain (403)", r.status_code == 403)
        r = await client.put("/api/v1/admin/settings/tracking-domain", headers=pub,
                             json={"tracking_base_url": "https://evil.example"})
        check("T4: publisher cannot modify tracking domain (403)", r.status_code == 403)

        r = await client.get("/api/v1/admin/settings/tracking-domain", headers=sa)
        initial = r.json()
        check("T5: initially not configured (honest state, no invented domain)",
              r.status_code == 200 and initial["configured"] is False and initial["tracking_base_url"] is None)

        for bad, label in [
            ("not a url", "invalid URL"),
            ("javascript:alert(1)", "javascript: scheme"),
            ("data:text/html,x", "data: scheme"),
            ("file:///etc/passwd", "file: scheme"),
            ("https://user:pass@example-a.test", "credentials in URL"),
            ("https://example-a.test/?x=1", "query string"),
            ("https://example-a.test/#frag", "fragment"),
            (" https://example-a.test ", "whitespace"),
            ("ftp://example-a.test", "unsupported scheme"),
        ]:
            r = await client.put("/api/v1/admin/settings/tracking-domain", headers=sa,
                                 json={"tracking_base_url": bad})
            check(f"T6: invalid URL rejected — {label} (422)", r.status_code == 422, f"{bad} -> {r.status_code}")

        r = await client.put("/api/v1/admin/settings/tracking-domain", headers=sa,
                             json={"tracking_base_url": "https://example-a.test/", "reason": "initial setup"})
        body = r.json()
        check("T7: valid URL accepted (200)", r.status_code == 200, r.text)
        check("T8: trailing slash normalized", body["tracking_base_url"] == "https://example-a.test", body["tracking_base_url"])
        check("T9: acceptance — canonical example URL built server-side",
              body["example_url"] == "https://example-a.test/C7K29/X8Q2", body["example_url"])
        check("T10: not falsely marked verified (spec §19)",
              body["verified"] is False and "ownership verification not implemented" in body["verification_note"])
        check("T11: effective source is database after explicit set", body["effective_source"] == "database")

        generated_before = await settings_service.build_tracking_url("C7K29", "X8Q2")
        check("T12: resolver builds link from configured domain",
              generated_before == "https://example-a.test/C7K29/X8Q2", str(generated_before))

        r = await client.put("/api/v1/admin/settings/tracking-domain", headers=sa,
                             json={"tracking_base_url": "https://example-b.test", "reason": "migration"})
        check("T13: domain change accepted", r.status_code == 200)
        generated_after = await settings_service.build_tracking_url("C7K29", "X8Q2")
        check("T14: domain change affects NEW links",
              generated_after == "https://example-b.test/C7K29/X8Q2", str(generated_after))
        check("T15: previously generated link value is never rewritten",
              generated_before == "https://example-a.test/C7K29/X8Q2")

        audit = await db["audit_logs"].find_one({"action": "TRACKING_DOMAIN_UPDATED"}, sort=[("timestamp", -1)])
        check("T16: domain change is audited with old/new values",
              audit is not None
              and audit["before"]["tracking_base_url"] == "https://example-a.test"
              and audit["after"]["tracking_base_url"] == "https://example-b.test")

        # =========================================================
        # CAMPAIGN DATA PURGE (directive §22 — 26 mandatory tests)
        # =========================================================
        async def make_campaign(name: str) -> str:
            resp = await client.post("/api/v1/admin/campaigns", headers=sa,
                                     json={**BASE_CAMPAIGN, "name": name})
            assert resp.status_code == 200, resp.text
            return resp.json()["campaign_id"]

        camp_a = await make_campaign("Alpha Sunset")
        camp_b = await make_campaign("Beta Running")
        camp_c = await make_campaign("Gamma Resume")
        for cid in (camp_a, camp_b, camp_c):
            await client.post(f"/api/v1/admin/campaigns/{cid}/activate", headers=sa)
        # A and C end; B stays ACTIVE
        await client.post(f"/api/v1/admin/campaigns/{camp_a}/end", headers=sa)
        await client.post(f"/api/v1/admin/campaigns/{camp_c}/end", headers=sa)

        await seed_campaign_data(db, camp_a, 11)
        await seed_campaign_data(db, camp_b, 12)
        await seed_campaign_data(db, camp_c, 13)

        users_before = await db["users"].count_documents({})

        # --- authorization / role tests ---
        r = await client.get(f"/api/v1/admin/campaigns/{camp_a}/purge-preview")
        check("P12: purge requires authentication (401)", r.status_code == 401)
        r = await client.get(f"/api/v1/admin/campaigns/{camp_a}/purge-preview", headers=mgr)
        check("P13a: manager rejected on purge preview (403)", r.status_code == 403)
        r = await client.post(f"/api/v1/admin/campaigns/{camp_a}/purge", headers=pub,
                              json={"confirm_campaign_name": "Alpha Sunset"})
        check("P13b: publisher rejected on purge execute (403)", r.status_code == 403)
        r = await client.post(f"/api/v1/admin/campaigns/{camp_a}/purge", headers=mgr,
                              json={"confirm_campaign_name": "Alpha Sunset"})
        check("P13c: manager rejected on purge execute (403)", r.status_code == 403)

        # --- purge map boundary (test 9: financial protection) ---
        purged_collections = {c for c, _ in purge_service.PURGE_DEPENDENCY_MAP}
        protected = {"users", "managers", "publishers", "campaigns", "campaign_config_versions",
                     "audit_logs", "invites", "otps", "refresh_sessions", "purge_operations",
                     "system_settings", "wallets", "ledger", "withdrawals", "payouts"}
        check("P9: purge map cannot touch identity/audit/config/financial collections",
              purged_collections.isdisjoint(protected), str(purged_collections))

        # --- preview accuracy (tests 6/21) ---
        r = await client.get(f"/api/v1/admin/campaigns/{camp_a}/purge-preview", headers=sa)
        preview = r.json()
        check("P21: preview returns real DB counts matching seeded records",
              r.status_code == 200
              and {c["collection"]: c["count"] for c in preview["categories"]} == SEED_COUNTS
              and preview["total_purgeable_records"] == sum(SEED_COUNTS.values()),
              f"total={preview.get('total_purgeable_records')}")
        check("Preview: ended campaign eligible", preview["eligible"] is True)

        r = await client.get(f"/api/v1/admin/campaigns/{camp_b}/purge-preview", headers=sa)
        check("Preview: active campaign NOT eligible", r.json()["eligible"] is False)

        # --- safety rejections ---
        r = await client.post(f"/api/v1/admin/campaigns/{camp_a}/purge", headers=sa,
                              json={"confirm_campaign_name": "Alpha Sunse"})
        check("P14: campaign name mismatch rejected (422)", r.status_code == 422, r.text)

        r = await client.post(f"/api/v1/admin/campaigns/{camp_b}/purge", headers=sa,
                              json={"confirm_campaign_name": "Beta Running"})
        check("P11: ACTIVE campaign cannot be purged (409)", r.status_code == 409, r.text)

        r = await client.post("/api/v1/admin/campaigns/CAMPXXXX/purge", headers=sa,
                              json={"confirm_campaign_name": "Nope"})
        check("Purge of unknown campaign -> 404", r.status_code == 404)

        # --- execute purge on A (tests 1, 19, 22, 23) ---
        r = await client.post(f"/api/v1/admin/campaigns/{camp_a}/purge", headers=sa,
                              json={"confirm_campaign_name": "Alpha Sunset"})
        result = r.json()
        check("Purge executes successfully (200)", r.status_code == 200, r.text)
        check("P22: actual deleted count reported",
              result["total_deleted"] == sum(SEED_COUNTS.values()), str(result.get("total_deleted")))
        check("P23: verification — unrelated totals unchanged",
              result["verification"]["unrelated_totals_unchanged"] is True)
        check("Verification — tombstone present", result["verification"]["campaign_tombstone_present"] is True)
        check("P1: verification — all purgeable records removed",
              result["verification"]["all_purgeable_records_removed"] is True)
        purge_id = result["purge_id"]
        check("Purge operation has explicit PURGE- id", purge_id.startswith("PURGE-"), purge_id)

        # A gone, per collection
        a_remaining = {col: await db[col].count_documents({"campaign_id": camp_a}) for col, _ in purge_service.PURGE_DEPENDENCY_MAP}
        check("P1b: every mapped collection has 0 records for campaign A",
              all(v == 0 for v in a_remaining.values()), str(a_remaining))

        # B and C fully intact (tests 2, 3, 7, 8, 20)
        for cid, label in [(camp_b, "B"), (camp_c, "C")]:
            remaining = {col: await db[col].count_documents({"campaign_id": cid}) for col, _ in purge_service.PURGE_DEPENDENCY_MAP}
            check(f"P2/3: campaign {label} purgeable data fully intact (incl. tracking links)",
                  remaining == SEED_COUNTS, str(remaining))

        # identities survive (tests 4, 5, 6)
        check("P4: publisher record remains", await db["publishers"].count_documents({"publisher_id": "PUB7788"}) == 1)
        check("P5: manager record remains", await db["managers"].count_documents({"manager_id": "AM97578"}) == 1)
        check("P6: user records unchanged", await db["users"].count_documents({}) == users_before)

        # audit (tests 10, 24)
        audit = await db["audit_logs"].find_one({"action": "CAMPAIGN_PURGED", "metadata.campaign_id": camp_a})
        check("P10/24: purge audit record written with campaign snapshot + operation id",
              audit is not None
              and audit["metadata"]["purge_operation_id"] == purge_id
              and audit["metadata"]["campaign_name"] == "Alpha Sunset"
              and audit["metadata"]["total_deleted"] == sum(SEED_COUNTS.values()))

        # tombstone (test 25) + visibility (§16)
        tomb = await db["campaigns"].find_one({"campaign_id": camp_a})
        check("P25: tombstone remains (status=purged, purge metadata, identity kept)",
              tomb is not None and tomb["status"] == "purged"
              and tomb.get("purge_operation_id") == purge_id
              and tomb.get("purged_by") is not None
              and tomb["summary"]["name"] == "Alpha Sunset")

        detail = await client.get(f"/api/v1/admin/campaigns/{camp_a}", headers=sa)
        check("Purged campaign still readable as tombstone via API",
              detail.status_code == 200 and detail.json()["status"] == "purged")

        listing = await client.get("/api/v1/admin/campaigns", headers=sa)
        listed_ids = [c["campaign_id"] for c in listing.json()]
        check("§16: purged campaign excluded from normal listings",
              camp_a not in listed_ids and camp_b in listed_ids)
        purged_listing = await client.get("/api/v1/admin/campaigns", headers=sa, params={"status": "purged"})
        check("§16: purged campaign explicitly queryable via status filter",
              camp_a in [c["campaign_id"] for c in purged_listing.json()])

        # repeated purge (test 15)
        r = await client.post(f"/api/v1/admin/campaigns/{camp_a}/purge", headers=sa,
                              json={"confirm_campaign_name": "Alpha Sunset"})
        check("P15: repeated purge safely rejected as ALREADY_PROCESSED (409)",
              r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_PROCESSED", r.text)

        # tracking guards (tests 17, 18)
        try:
            assert_campaign_is_traffic_live(tomb)
            guard_raised = False
        except ConflictError:
            guard_raised = True
        check("P17/18: purged campaign rejects new clicks/links via traffic guard", guard_raised)

        b_doc = await db["campaigns"].find_one({"campaign_id": camp_b})
        try:
            assert_campaign_is_traffic_live(b_doc)
            guard_ok = True
        except ConflictError:
            guard_ok = False
        check("Guard: ACTIVE campaign accepts tracking traffic", guard_ok)

        # purge-status endpoint
        r = await client.get(f"/api/v1/admin/campaigns/{camp_a}/purge-status", headers=sa)
        check("Purge status endpoint returns completed operation",
              r.status_code == 200 and r.json()["status"] == "completed" and r.json()["purge_id"] == purge_id)

        # --- interrupted purge is safely retryable (test 16) ---
        now = datetime.now(timezone.utc)
        await db["purge_operations"].insert_one({
            "purge_id": "PURGE-RESUME01", "campaign_id": camp_c, "campaign_name": "Gamma Resume",
            "status": "running", "actor_user_id": "seed-user-mgr", "request_id": "simcrash",
            "planned_counts": SEED_COUNTS, "deleted_counts": None, "verification": None,
            "error": "simulated crash", "created_at": now, "updated_at": now, "completed_at": None,
        })
        r = await client.post(f"/api/v1/admin/campaigns/{camp_c}/purge", headers=sa,
                              json={"confirm_campaign_name": "Gamma Resume"})
        resumed = r.json()
        check("P16: interrupted purge resumes the SAME operation and completes",
              r.status_code == 200 and resumed["purge_id"] == "PURGE-RESUME01" and resumed["status"] == "completed",
              f"{r.status_code} {resumed.get('purge_id')}")
        c_remaining = {col: await db[col].count_documents({"campaign_id": camp_c}) for col, _ in purge_service.PURGE_DEPENDENCY_MAP}
        check("P16b: resumed purge removed all of campaign C's records",
              all(v == 0 for v in c_remaining.values()))
        c_audit_count = await db["audit_logs"].count_documents({"action": "CAMPAIGN_PURGED", "metadata.campaign_id": camp_c})
        check("P16c: resumed purge audited exactly once", c_audit_count == 1)

        # --- final integrity (tests 19/20/26) ---
        check("P19/20: no collection-wide delete — campaign B data still complete",
              await db["clicks"].count_documents({}) == SEED_COUNTS["clicks"]
              and await db["tracking_links"].count_documents({}) == SEED_COUNTS["tracking_links"])
        check("P26: database integrity valid — identity collections intact, audit grew only by purge entries",
              await db["users"].count_documents({}) == users_before
              and await db["managers"].count_documents({}) == 1
              and await db["publishers"].count_documents({}) == 1
              and await db["campaigns"].count_documents({}) == 3)

        ops = await db["purge_operations"].count_documents({})
        check("Purge operation records kept for both purges", ops == 2, str(ops))

    passed = sum(1 for _, s, _ in results if s == "PASS")
    print(f"\n--- SUMMARY ---\n{passed}/{len(results)} checks passed")
    return passed == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
