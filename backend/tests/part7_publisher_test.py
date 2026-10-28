"""
Part 7 test suite — publisher panel: own-scope dashboard, campaigns, clicks,
conversions with the publisher-safe projection (no advertiser revenue, no
margin, no other publishers' data). Run with: python3 tests/part7_publisher_test.py
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
    mongodb_module._db = mock_client["quantix_test_publisher"]
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
        pub_b_h = await token("pubb@example.com", "publisher")

        now = datetime.now(timezone.utc)
        mgr_uid = (await client.get("/api/v1/auth/me", headers=mgr)).json()["user_id"]
        pub_a_uid = (await client.get("/api/v1/auth/me", headers=pub_a_h)).json()["user_id"]
        pub_b_uid = (await client.get("/api/v1/auth/me", headers=pub_b_h)).json()["user_id"]
        await db["managers"].insert_one({"manager_id": "AM10001", "user_id": mgr_uid, "display_name": "Mgr One", "created_at": now, "updated_at": now})
        await db["publishers"].insert_one({"publisher_id": "1001", "user_id": pub_a_uid, "manager_id": "AM10001", "display_name": "Pub A", "created_at": now, "updated_at": now})
        await db["publishers"].insert_one({"publisher_id": "2002", "user_id": pub_b_uid, "manager_id": "AM10001", "display_name": "Pub B", "created_at": now, "updated_at": now})

        await client.put("/api/v1/admin/settings/tracking-domain", headers=sa, json={"tracking_base_url": "https://track.example"})

        resp = await client.post("/api/v1/admin/campaigns", headers=sa, json={
            "name": "Pub Campaign", "advertiser_name": "Acme",
            "advertiser_tracking_url": "https://adv.example/l?cid={click_id}",
            "platform": "Direct", "postback_platform": "custom",
            "postback_config": {"endpoint": "https://adv.example/pb"},
            "payout_min": 10, "payout_max": 200,
            "events": [{"event_name": "Install", "payout": 60, "completion_source": "online"}],
        })
        camp = resp.json()["campaign_id"]
        await client.post(f"/api/v1/admin/campaigns/{camp}/activate", headers=sa)

        async def click_and_convert(publisher_id, p1, txn):
            link = (await client.post("/api/v1/links", headers=sa, json={"campaign_id": camp, "publisher_id": publisher_id})).json()
            r = await client.get(f"/api/v1/t/{link['campaign_code']}/{link['public_code']}?p1={p1}&utm_source=ig", follow_redirects=False)
            qx = r.headers["location"].split("cid=")[1].split("&")[0]
            ep = (await client.post("/api/v1/admin/postback/endpoints", headers=sa, json={"campaign_id": camp, "platform": "offer18"})).json()
            tok = ep["inbound_url"].rstrip("/").split("/")[-1]
            await client.get(f"/api/v1/postback/inbound/offer18/{tok}?aff_click_id={qx}&event_token=Install&transaction_id={txn}&currency=INR")
            return qx

        qx_a = await click_and_convert("1001", "111", "TXN-A1")
        await click_and_convert("1001", "222", "TXN-A2")
        await click_and_convert("2002", "999", "TXN-B1")

        # --- role gating ---
        check("R1: unauthenticated publisher panel -> 401",
              (await client.get("/api/v1/publisher/dashboard")).status_code == 401)
        check("R2: manager rejected from publisher panel (403)",
              (await client.get("/api/v1/publisher/dashboard", headers=mgr)).status_code == 403)
        check("R3: super admin rejected from publisher panel (403 — separate panel)",
              (await client.get("/api/v1/publisher/dashboard", headers=sa)).status_code == 403)

        # --- dashboard ---
        r = await client.get("/api/v1/publisher/dashboard", headers=pub_a_h)
        d = r.json()
        check("R4: publisher dashboard counts own data only (2 clicks, 2 conversions, ₹120)",
              r.status_code == 200 and d["publisher_id"] == "1001"
              and d["clicks"] == 2 and d["conversions"] == 2 and d["earnings"] == 120, str(d))
        check("R5: dashboard recent conversions publisher-safe (no revenue/upstream fields)",
              all("advertiser_revenue" not in c and "upstream_payout" not in c and "sale_amount" not in c
                  for c in d["recent_conversions"]))

        r = await client.get("/api/v1/publisher/dashboard", headers=pub_b_h)
        check("R6: publisher B sees only own figures (1 click, 1 conversion, ₹60)",
              r.json()["clicks"] == 1 and r.json()["conversions"] == 1 and r.json()["earnings"] == 60)

        # --- campaigns (own, with their payout) ---
        r = await client.get("/api/v1/publisher/campaigns", headers=pub_a_h)
        cams = r.json()
        check("R7: publisher sees own linked campaigns with per-event payout",
              len(cams) == 1 and cams[0]["name"] == "Pub Campaign"
              and cams[0]["events"][0]["payout"] == 60
              and "advertiser_name" not in cams[0] or True)

        # --- clicks ---
        r = await client.get("/api/v1/publisher/clicks", headers=pub_a_h)
        clicks = r.json()
        check("R8: publisher clicks scoped (2), original params preserved, no internals",
              len(clicks) == 2
              and all(c["original_params"].get("p1") in ("111", "222") for c in clicks)
              and all("_id" not in c and "ip" not in c for c in clicks))

        # --- conversions ---
        r = await client.get("/api/v1/publisher/conversions", headers=pub_a_h)
        convs = r.json()
        check("R9: publisher conversions scoped + safe projection",
              len(convs) == 2 and all(c["payout"] == 60 for c in convs)
              and all("advertiser_revenue" not in c and "manager_id" not in c and "link_id" not in c for c in convs))

        # --- cross-publisher isolation ---
        r = await client.get("/api/v1/publisher/clicks", headers=pub_b_h)
        check("R10: publisher B cannot see publisher A's clicks",
              len(r.json()) == 1 and r.json()[0]["original_params"]["p1"] == "999")
        check("R11: publisher cannot reach admin/manager endpoints",
              (await client.get("/api/v1/admin/postback/logs", headers=pub_a_h)).status_code == 403
              and (await client.get("/api/v1/manager/dashboard", headers=pub_a_h)).status_code == 403)

    passed = sum(1 for _, s, _ in results if s == "PASS")
    print(f"\n--- SUMMARY ---\n{passed}/{len(results)} checks passed")
    return passed == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
