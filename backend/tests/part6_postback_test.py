"""
Part 6 test suite — conversions + inbound platform adapters (Offer18/Trackier/
Trackix) + idempotency + outbound publisher postbacks with per-publisher
macro routing. Run with: python3 tests/part6_postback_test.py
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


async def main():
    from bson import ObjectId
    from mongomock_motor import AsyncMongoMockClient
    import app.db.mongodb as mongodb_module

    mock_client = AsyncMongoMockClient()
    mongodb_module._client = mock_client
    mongodb_module._db = mock_client["quantix_test_postbacks"]
    await mongodb_module.ensure_indexes(mongodb_module._db)
    db = mongodb_module._db

    from httpx import AsyncClient, ASGITransport
    from app.main import create_app
    from app.services import postback_service

    app = create_app()

    # Outbound HTTP delivery is patched to capture URLs instead of real network
    delivered_urls: list[str] = []

    async def fake_http_get(url):
        delivered_urls.append(url)
        return 200, "OK", None

    postback_service._http_get = fake_http_get

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async def token(email, role):
            r = await client.post("/api/v1/auth/_dev/issue-token", params={"email": email, "role": role})
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        sa = await token("superadmin@example.com", "super_admin")
        mgr = await token("manager1@example.com", "manager")
        pub_a_h = await token("puba@example.com", "publisher")
        pub_b_h = await token("pubb@example.com", "publisher")

        now = datetime.now(timezone.utc)
        mgr_uid = (await client.get("/api/v1/auth/me", headers=mgr)).json()["user_id"]
        pub_a_uid = (await client.get("/api/v1/auth/me", headers=pub_a_h)).json()["user_id"]
        pub_b_uid = (await client.get("/api/v1/auth/me", headers=pub_b_h)).json()["user_id"]
        await db["managers"].insert_one({"manager_id": "AM10001", "user_id": mgr_uid, "display_name": "Mgr One", "created_at": now, "updated_at": now})
        await db["managers"].insert_one({"manager_id": "AM10002", "user_id": str(ObjectId()), "display_name": "Mgr Two", "created_at": now, "updated_at": now})
        await db["publishers"].insert_one({"publisher_id": "1001", "user_id": pub_a_uid, "manager_id": "AM10001", "display_name": "Pub A", "created_at": now, "updated_at": now})
        await db["publishers"].insert_one({"publisher_id": "2002", "user_id": pub_b_uid, "manager_id": "AM10002", "display_name": "Pub B", "created_at": now, "updated_at": now})

        await client.put("/api/v1/admin/settings/tracking-domain", headers=sa,
                         json={"tracking_base_url": "https://track.example"})

        async def make_campaign(name, events):
            resp = await client.post("/api/v1/admin/campaigns", headers=sa, json={
                "name": name, "advertiser_name": "Acme",
                "advertiser_tracking_url": "https://adv.example/l?cid={click_id}",
                "platform": "Direct", "postback_platform": "custom",
                "postback_config": {"endpoint": "https://adv.example/pb"},
                "payout_min": 10, "payout_max": 200, "events": events,
            })
            cid = resp.json()["campaign_id"]
            await client.post(f"/api/v1/admin/campaigns/{cid}/activate", headers=sa)
            return cid

        events = [{"event_name": "Install", "payout": 60, "completion_source": "online"},
                  {"event_name": "Register", "payout": 95, "completion_source": "online"}]
        camp_a = await make_campaign("Conv Campaign", events)
        camp_b = await make_campaign("Other Campaign", events)

        async def make_click(campaign_id, publisher_id, query):
            link = (await client.post("/api/v1/links", headers=sa,
                                      json={"campaign_id": campaign_id, "publisher_id": publisher_id})).json()
            r = await client.get(f"/api/v1/t/{link['campaign_code']}/{link['public_code']}?{query}", follow_redirects=False)
            assert r.status_code == 302, r.text
            loc = r.headers["location"]
            return loc.split("cid=")[1].split("&")[0]

        # Publisher A: p1 = UPI, p2 = Name. Publisher B: p1 = Name, p2 = UPI, p3 = OrderID.
        click_a = await make_click(camp_a, "1001", "p1=9876543210&p2=Suraj&utm_source=facebook")
        click_b = await make_click(camp_a, "2002", "p1=Rahul&p2=rahul@upi&p3=ORD9988")

        # --- platform metadata (drives Postback Setup UI) ---
        r = await client.get("/api/v1/admin/postback/platforms", headers=sa)
        meta = r.json()
        check("B1: platform metadata exposes Offer18/Trackier required params, Trackix honestly unverified",
              r.status_code == 200 and "aff_click_id" in meta["offer18"]["required"]
              and "goal_value" in meta["trackier"]["required"] and meta["trackix"]["verified"] is False)
        check("B2: manager/publisher rejected from postback admin (403)",
              (await client.get("/api/v1/admin/postback/platforms", headers=mgr)).status_code == 403
              and (await client.get("/api/v1/admin/postback/platforms", headers=pub_a_h)).status_code == 403)

        # --- endpoint creation ---
        r = await client.post("/api/v1/admin/postback/endpoints", headers=sa,
                              json={"campaign_id": camp_a, "platform": "offer18"})
        ep = r.json()
        check("B3: endpoint created with full inbound URL", r.status_code == 200 and "/api/v1/postback/inbound/offer18/" in ep["inbound_url"])
        ep_token = ep["inbound_url"].rstrip("/").split("/")[-1]
        r = await client.post("/api/v1/admin/postback/endpoints", headers=sa,
                              json={"campaign_id": camp_b, "platform": "offer18"})
        ep_b_token = r.json()["inbound_url"].rstrip("/").split("/")[-1]
        r = await client.get("/api/v1/admin/postback/endpoints", headers=sa)
        check("B4: endpoint list never leaks tokens", all("token" not in e and "inbound_url" not in e for e in r.json()))
        check("B5: unsupported platform rejected (422)",
              (await client.post("/api/v1/admin/postback/endpoints", headers=sa,
                                 json={"campaign_id": camp_a, "platform": "madeup"})).status_code == 422)

        # --- publisher outbound configs (before conversions, so they fire) ---
        r = await client.put("/api/v1/admin/postback/publisher-config", headers=pub_a_h,
                             json={"url": "https://pub-a.example/pb?cid={click_id}&upi={p1}&name={p2}&ev={event}"})
        check("O1: publisher saves own postback config (version 1)",
              r.status_code == 200 and r.json()["version"] == 1, r.text)
        r = await client.put("/api/v1/admin/postback/publisher-config", headers=pub_a_h,
                             json={"url": "https://pub-a.example/v2?cid={click_id}&upi={p1}&name={p2}&ev={event}"})
        check("O2: config change creates version 2 (no silent overwrite)", r.json()["version"] == 2)
        check("O3: unknown macro rejected (422)",
              (await client.put("/api/v1/admin/postback/publisher-config", headers=pub_a_h,
                                json={"url": "https://pub-a.example/x?e={hack}"})).status_code == 422)
        check("O4: SSRF — loopback/private URL rejected (422)",
              (await client.put("/api/v1/admin/postback/publisher-config", headers=pub_a_h,
                                json={"url": "http://127.0.0.1/internal?c={click_id}"})).status_code == 422)
        r = await client.get("/api/v1/admin/postback/publisher-config", headers=pub_a_h)
        check("O5: publisher reads own active config", r.json()["configured"] is True and "v2" in r.json()["url_template"])
        r = await client.get("/api/v1/admin/postback/publisher-config", headers=pub_b_h)
        check("O6: publisher B isolated (no config visible)", r.json()["configured"] is False)
        await client.put("/api/v1/admin/postback/publisher-config", headers=pub_b_h,
                         json={"url": "https://pub-b.example/pb?name={p1}&upi={p2}&order={p3}&cid={click_id}"})

        # --- Offer18 inbound ---
        url_a = f"/api/v1/postback/inbound/offer18/{ep_token}"
        r = await client.get(f"{url_a}?aff_click_id={click_a}&event_token=Install&payout=9999&currency=INR&sub_aff_id=AG1&aff_sub1=src1")
        check("P1: Offer18 postback accepted", r.status_code == 200 and r.json()["status"] == "ok", r.text)
        conv = await db["conversions"].find_one({"digisnr_click_id": click_a})
        check("P2: conversion stores event + raw event + currency + agency id separately",
              conv["event"] == "Install" and conv["raw_event_value"] == "Install"
              and conv["currency"] == "INR" and conv["agency_click_id"] == "AG1")
        check("P3: payout comes from campaign config (₹60), NOT the postback's 9999",
              conv["payout"] == 60)
        check("P4: server-authoritative identity from the click (publisher/manager/link)",
              conv["publisher_id"] == "1001" and conv["manager_id"] == "AM10001")
        check("P5: timestamps — postback_received_at set, click_created_at preserved",
              conv.get("postback_received_at") is not None and conv.get("click_created_at") is not None)
        check("P6: transport subs preserved (aff_sub1)",
              conv["sub_ids"].get("aff_sub1") == "src1")

        # duplicate → idempotent
        await client.get(f"{url_a}?aff_click_id={click_a}&event_token=Install&payout=9999&currency=INR&sub_aff_id=AG1")
        count = await db["conversions"].count_documents({"digisnr_click_id": click_a, "event": "Install"})
        dup_log = await db["inbound_postbacks"].count_documents({"processing_status": "duplicate"})
        check("P7: duplicate postback — no second conversion, logged as duplicate",
              count == 1 and dup_log == 1)

        # --- outbound fired with publisher A's mapping ---
        out = await db["outbound_postbacks"].find_one({"publisher_id": "1001"})
        check("O7: outbound fired to publisher A config with ORIGINAL click params",
              out is not None and "upi=9876543210" in out["url"] and "name=Suraj" in out["url"]
              and "ev=" in out["url"] and out["url"].startswith("https://pub-a.example/v2")
              and out["final_status"] == "delivered" and out["attempt_count"] == 1, (out or {}).get("url", "NONE"))

        # --- Trackier inbound (publisher B's click) ---
        url_tk = f"/api/v1/postback/inbound/trackier/{(await client.post('/api/v1/admin/postback/endpoints', headers=sa, json={'campaign_id': camp_a, 'platform': 'trackier'})).json()['inbound_url'].rstrip('/').split('/')[-1]}"
        r = await client.get(f"{url_tk}?click_id={click_b}&txn_id=TXN99&goal_value=Register&status=approved&revenue=250&sale_amount=500&currency=INR&sub2=zz")
        check("P8: Trackier postback accepted", r.status_code == 200 and r.json()["status"] == "ok")
        conv_b = await db["conversions"].find_one({"digisnr_click_id": click_b})
        check("P9: Trackier fields mapped — txn_id, goal_value, status, revenue, sale_amount, currency",
              conv_b["external_conversion_id"] == "TXN99" and conv_b["goal"] == "Register"
              and conv_b["raw_goal_value"] == "Register" and conv_b["status"] == "approved"
              and conv_b["advertiser_revenue"] == "250" and conv_b["sale_amount"] == "500"
              and conv_b["currency"] == "INR" and conv_b["payout"] == 95)

        # §18 routing rule — publisher B's OWN meaning of p1/p2/p3
        out_b = await db["outbound_postbacks"].find_one({"publisher_id": "2002"})
        check("O8: publisher B mapping routes p1=Name, p2=UPI, p3=OrderID (NOT p1=UPI)",
              out_b is not None and "name=Rahul" in out_b["url"] and "upi=rahul%40upi" in out_b["url"]
              and "order=ORD9988" in out_b["url"], (out_b or {}).get("url", "NONE"))

        # legitimate status update on the same conversion
        await client.get(f"{url_tk}?click_id={click_b}&txn_id=TXN99&goal_value=Register&status=rejected&currency=INR")
        conv_b2 = await db["conversions"].find_one({"digisnr_click_id": click_b})
        total_b = await db["conversions"].count_documents({"digisnr_click_id": click_b})
        audit_upd = await db["audit_logs"].find_one({"action": "CONVERSION_STATUS_UPDATED"})
        check("P10: status update modifies existing conversion, never duplicates",
              conv_b2["status"] == "rejected" and conv_b2["raw_status"] == "rejected" and total_b == 1 and audit_upd is not None)

        # --- negative paths ---
        await client.get(f"{url_a}?aff_click_id={click_a}&event_token=NoSuchEvent")
        conv_unk = await db["conversions"].find_one({"digisnr_click_id": click_a, "event": "NoSuchEvent"})
        check("P11: unknown event recorded honestly (payout None + note)",
              conv_unk is not None and conv_unk["payout"] is None and conv_unk["payout_note"] == "no_matching_event")

        r = await client.get(f"{url_a}?aff_click_id=QXCLK_UNKNOWN99&event_token=Install")
        unresolved = await db["inbound_postbacks"].count_documents({"processing_status": "unresolved"})
        check("P12: unresolvable click → 200 ack + unresolved log, NO conversion (never guess)",
              r.status_code == 200 and unresolved >= 1)

        r = await client.get(f"/api/v1/postback/inbound/offer18/{ep_b_token}?aff_click_id={click_a}&event_token=Install")
        check("P13: click from another campaign cannot convert on this endpoint (anti-forgery)",
              r.status_code == 200
              and await db["conversions"].count_documents({"campaign_id": camp_b}) == 0)

        check("P14: wrong token → 404 (nothing leaks)",
              (await client.get(f"{url_a}x")).status_code == 404
              and (await client.get("/api/v1/postback/inbound/offer18/not-a-token")).status_code == 404)
        r = await client.post(url_a, json={}, headers={"Content-Type": "application/json"})
        check("P15: empty/malformed postback → 400", r.status_code == 400)

        ep_list = (await client.get("/api/v1/admin/postback/endpoints", headers=sa, params={"campaign_id": camp_a})).json()
        ep_id = next(e["endpoint_id"] for e in ep_list if e["platform"] == "offer18")
        await client.post(f"/api/v1/admin/postback/endpoints/{ep_id}/disable", headers=sa)
        disabled_hits = await db["inbound_postbacks"].count_documents({})
        r = await client.get(f"{url_a}?aff_click_id={click_a}&event_token=Install")
        check("P16: disabled endpoint → 404, nothing logged",
              r.status_code == 404 and await db["inbound_postbacks"].count_documents({}) == disabled_hits)

        # --- outbound retries + manual refire ---
        async def failing_http_get(url):
            return None, None, "connection refused"

        postback_service._http_get = failing_http_get
        url_a2 = f"/api/v1/postback/inbound/offer18/{ep_token}"
        # re-enable endpoint first
        await client.post(f"/api/v1/admin/postback/endpoints/{ep_id}/enable", headers=sa)
        click_c = await make_click(camp_a, "1001", "p1=555&p2=Meena")
        r = await client.get(f"{url_a2}?aff_click_id={click_c}&event_token=Register&currency=INR")
        failed_out = await db["outbound_postbacks"].find_one({"conversion_id": (await db['conversions'].find_one({'digisnr_click_id': click_c}))['conversion_id']})
        check("O9: failed delivery retries to 4 total attempts, final_status=failed",
              failed_out["attempt_count"] == 4 and failed_out["final_status"] == "failed")

        postback_service._http_get = fake_http_get
        r = await client.post(f"/api/v1/admin/postback/outbound/{failed_out['outbound_id']}/refire", headers=sa)
        check("O10: manual refire delivers + is audited",
              r.status_code == 200 and r.json()["final_status"] == "delivered" and r.json()["attempt_count"] == 5
              and await db["audit_logs"].find_one({"action": "OUTBOUND_POSTBACK_REFIRED"}) is not None)
        check("O11: refire rejected for publisher role (403)",
              (await client.post(f"/api/v1/admin/postback/outbound/{failed_out['outbound_id']}/refire", headers=pub_a_h)).status_code == 403)

        # --- logs API ---
        r = await client.get("/api/v1/admin/postback/logs", headers=sa, params={"platform": "offer18"})
        check("B6: inbound logs filterable by platform, carry processing status",
              r.status_code == 200 and len(r.json()) >= 3 and all(l["platform"] == "offer18" for l in r.json()))
        r = await client.get("/api/v1/admin/postback/logs", headers=mgr)
        check("B7: manager cannot read postback logs (403)", r.status_code == 403)

        # --- purge integration: campaign-scoped data all purged ---
        click_b2 = await make_click(camp_b, "1001", "p1=7")
        await client.get(f"/api/v1/postback/inbound/offer18/{ep_b_token}?aff_click_id={click_b2}&event_token=Install")
        await client.post(f"/api/v1/admin/campaigns/{camp_b}/end", headers=sa)
        r = await client.post(f"/api/v1/admin/campaigns/{camp_b}/purge", headers=sa, json={"confirm_campaign_name": "Other Campaign"})
        check("P17: purge removes campaign B conversions + postback endpoints + logs",
              r.status_code == 200
              and await db["conversions"].count_documents({"campaign_id": camp_b}) == 0
              and await db["postback_endpoints"].count_documents({"campaign_id": camp_b}) == 0
              and await db["inbound_postbacks"].count_documents({"campaign_id": camp_b}) == 0)
        check("P18: campaign A conversions untouched by B's purge",
              await db["conversions"].count_documents({"campaign_id": camp_a}) >= 3)

    passed = sum(1 for _, s, _ in results if s == "PASS")
    print(f"\n--- SUMMARY ---\n{passed}/{len(results)} checks passed")
    return passed == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
