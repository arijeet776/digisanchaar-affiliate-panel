"""
Part 8 test suite — reporting: network totals, group-by drilldowns, filters,
CSV export, manager scope pinning, publisher projection safety.
Run with: python3 tests/part8_reports_test.py
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
    mongodb_module._db = mock_client["quantix_test_reports"]
    await mongodb_module.ensure_indexes(mongodb_module._db)
    db = mongodb_module._db

    from httpx import AsyncClient, ASGITransport
    from app.main import create_app
    from app.services import postback_service

    async def fake_http_get(url):
        return 200, "OK", None

    postback_service._http_get = fake_http_get
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async def token(email, role):
            r = await client.post("/api/v1/auth/_dev/issue-token", params={"email": email, "role": role})
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        sa = await token("superadmin@example.com", "super_admin")
        mgr = await token("manager1@example.com", "manager")
        pub_a_h = await token("puba@example.com", "publisher")

        now = datetime.now(timezone.utc)
        mgr_uid = (await client.get("/api/v1/auth/me", headers=mgr)).json()["user_id"]
        pub_a_uid = (await client.get("/api/v1/auth/me", headers=pub_a_h)).json()["user_id"]
        await db["managers"].insert_one({"manager_id": "AM10001", "user_id": mgr_uid, "display_name": "Mgr One", "created_at": now, "updated_at": now})
        await db["managers"].insert_one({"manager_id": "AM10002", "user_id": str(ObjectId()), "display_name": "Mgr Two", "created_at": now, "updated_at": now})
        await db["publishers"].insert_one({"publisher_id": "1001", "user_id": pub_a_uid, "manager_id": "AM10001", "display_name": "Pub A", "created_at": now, "updated_at": now})
        pub_b_uid = str(ObjectId())
        await db["users"].insert_one({
            "_id": ObjectId(pub_b_uid), "email": "pubb@example.com", "password_hash": "x", "role": "publisher",
            "account_status": "active", "email_verified": True, "created_at": now, "updated_at": now,
        })
        await db["publishers"].insert_one({"publisher_id": "2002", "user_id": pub_b_uid, "manager_id": "AM10002", "display_name": "Pub B", "created_at": now, "updated_at": now})

        await client.put("/api/v1/admin/settings/tracking-domain", headers=sa, json={"tracking_base_url": "https://track.example"})

        resp = await client.post("/api/v1/admin/campaigns", headers=sa, json={
            "name": "Report Campaign", "advertiser_name": "Acme",
            "advertiser_tracking_url": "https://adv.example/l?cid={click_id}",
            "platform": "Direct", "postback_platform": "custom",
            "postback_config": {"endpoint": "https://adv.example/pb"},
            "payout_min": 10, "payout_max": 200,
            "events": [{"event_name": "Install", "payout": 60, "completion_source": "online"}],
        })
        camp = resp.json()["campaign_id"]
        await client.post(f"/api/v1/admin/campaigns/{camp}/activate", headers=sa)

        async def click_and_convert(publisher_id, txn, revenue=None):
            link = (await client.post("/api/v1/links", headers=sa, json={"campaign_id": camp, "publisher_id": publisher_id})).json()
            r = await client.get(f"/api/v1/t/{link['campaign_code']}/{link['public_code']}", follow_redirects=False)
            qx = r.headers["location"].split("cid=")[1].split("&")[0]
            ep = (await client.post("/api/v1/admin/postback/endpoints", headers=sa, json={"campaign_id": camp, "platform": "offer18"})).json()
            tok = ep["inbound_url"].rstrip("/").split("/")[-1]
            q = f"aff_click_id={qx}&event_token=Install&transaction_id={txn}&currency=INR"
            if revenue:
                q += f"&payout={revenue}"
            await client.get(f"/api/v1/postback/inbound/offer18/{tok}?{q}")

        # 2 clicks + 2 conversions for publisher A (mgr AM10001), 1 + 1 for B (mgr AM10002)
        await click_and_convert("1001", "T1")
        await click_and_convert("1001", "T2")
        await click_and_convert("2002", "T3")
        # one unattributed click for A
        link_a = next(l for l in (await client.get("/api/v1/links", headers=sa)).json() if l["publisher_id"] == "1001")
        await client.get(f"/api/v1/t/{link_a['campaign_code']}/{link_a['public_code']}", follow_redirects=False)

        # --- role gating ---
        check("G1: report endpoints reject unauthenticated (401)",
              (await client.get("/api/v1/admin/reports/summary")).status_code == 401)
        check("G2: publisher rejected from admin reports (403)",
              (await client.get("/api/v1/admin/reports/summary", headers=pub_a_h)).status_code == 403)
        check("G3: manager rejected from admin reports (403)",
              (await client.get("/api/v1/admin/reports/summary", headers=mgr)).status_code == 403)

        # --- admin network report ---
        r = await client.get("/api/v1/admin/reports/summary", headers=sa)
        body = r.json()
        check("G4: network totals — 4 clicks, 3 conversions, payout 180",
              body["totals"]["clicks"] == 4 and body["totals"]["conversions"] == 3 and body["totals"]["payout"] == 180,
              str(body["totals"]))
        check("G5: conversion rate computed (3/4 = 75%)", body["totals"]["conversion_rate"] == 75.0)

        r = await client.get("/api/v1/admin/reports/summary", headers=sa, params={"group_by": "publisher"})
        rows = {row["key"]: row for row in r.json()["rows"]}
        check("G6: group-by publisher drilldown — A: 2 conv / 3 clicks, B: 1 conv",
              rows["1001"]["conversions"] == 2 and rows["1001"]["clicks"] == 3 and rows["2002"]["conversions"] == 1, str(rows))

        r = await client.get("/api/v1/admin/reports/summary", headers=sa, params={"publisher_id": "1001"})
        check("G7: publisher filter narrows totals (3 clicks, 2 conversions)",
              r.json()["totals"]["clicks"] == 3 and r.json()["totals"]["conversions"] == 2)

        r = await client.get("/api/v1/admin/reports/summary", headers=sa, params={"event": "Install"})
        check("G8: event filter works (3 conversions)", r.json()["totals"]["conversions"] == 3)
        r = await client.get("/api/v1/admin/reports/summary", headers=sa, params={"event": "NoSuch"})
        check("G9: unknown event filter → zero conversions", r.json()["totals"]["conversions"] == 0)

        r = await client.get("/api/v1/admin/reports/summary", headers=sa,
                             params={"date_from": "2020-01-01T00:00:00Z", "date_to": "2020-01-02T00:00:00Z"})
        check("G10: date range filter works (2020 → 0)", r.json()["totals"]["conversions"] == 0)

        r = await client.get("/api/v1/admin/reports/export.csv", headers=sa, params={"group_by": "publisher"})
        text = r.text
        check("G11: CSV export with header + rows + TOTAL line",
              r.status_code == 200 and "text/csv" in r.headers["content-type"]
              and text.startswith("group,clicks,conversions") and "1001,3,2" in text and "TOTAL,4,3" in text, text[:120])

        # --- manager scope ---
        r = await client.get("/api/v1/admin/reports/manager/summary", headers=mgr)
        mt = r.json()["totals"]
        check("G12: manager report pinned to own scope (3 clicks / 2 conversions — not B's)",
              mt["clicks"] == 3 and mt["conversions"] == 2, str(mt))
        r = await client.get("/api/v1/admin/reports/manager/summary", headers=mgr, params={"publisher_id": "2002"})
        check("G13: manager filtering by another manager's publisher returns zero (scope wins)",
              r.json()["totals"]["conversions"] == 0)
        check("G14: publisher/super-admin cannot use manager report (403)",
              (await client.get("/api/v1/admin/reports/manager/summary", headers=pub_a_h)).status_code == 403
              and (await client.get("/api/v1/admin/reports/manager/summary", headers=sa)).status_code == 403)

        # --- publisher scope + projection ---
        r = await client.get("/api/v1/admin/reports/publisher/summary", headers=pub_a_h)
        pt = r.json()["totals"]
        check("G15: publisher report own scope (3 clicks / 2 conversions / payout 120)",
              pt["clicks"] == 3 and pt["conversions"] == 2 and pt["payout"] == 120)
        check("G16: publisher report NEVER includes revenue or margin",
              "revenue" not in pt and "margin" not in pt
              and all("revenue" not in row and "margin" not in row for row in r.json()["rows"]))
        check("G17: manager/admin rejected from publisher report (403)",
              (await client.get("/api/v1/admin/reports/publisher/summary", headers=mgr)).status_code == 403)

    passed = sum(1 for _, s, _ in results if s == "PASS")
    print(f"\n--- SUMMARY ---\n{passed}/{len(results)} checks passed")
    return passed == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
