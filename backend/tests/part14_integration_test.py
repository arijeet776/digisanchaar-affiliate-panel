"""
Part 14 cross-module integration test. Run with:
    python3 tests/part14_integration_test.py

Mongo is a mongomock double. Section 9 (earning -> withdrawal) needs a real
Postgres and is explicitly SKIPPED (never silently passed) unless POSTGRES_DSN
points at localhost.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

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


def skip(name, why):
    results.append((name, "SKIP", why))
    print(f"[SKIP] {name} — {why}")


async def main():
    from mongomock_motor import AsyncMongoMockClient
    import app.db.mongodb as mongodb_module

    mock_client = AsyncMongoMockClient()
    mongodb_module._client = mock_client
    mongodb_module._db = mock_client["quantix_test_part14"]
    await mongodb_module.ensure_indexes(mongodb_module._db)
    db = mongodb_module._db

    from httpx import AsyncClient, ASGITransport
    from app.main import create_app
    from app.services import postback_service, webhook_service

    async def fake_http_get(url):
        return 200, "OK", None

    postback_service._http_get = fake_http_get
    captured = []

    async def fake_http_post(url, payload, signature):
        captured.append({"payload": payload, "signature": signature})
        return 200, "OK"

    webhook_service._http_post = fake_http_post
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async def issue(email, role):
            r = await client.post("/api/v1/auth/_dev/issue-token", params={"email": email, "role": role})
            j = r.json()
            return {"Authorization": f"Bearer {j['access_token']}"}, j["refresh_token"]

        sa, _ = await issue("sa14@example.com", "super_admin")
        mgr1, _ = await issue("m1_14@example.com", "manager")
        mgr2, _ = await issue("m2_14@example.com", "manager")
        pub1, pub1_refresh = await issue("p1_14@example.com", "publisher")
        pub2, _ = await issue("p2_14@example.com", "publisher")

        # ---- 1. auth -> role ----
        me = await client.get("/api/v1/auth/me", headers=pub1)
        check("1a: publisher /me reports role publisher", me.status_code == 200 and me.json()["role"] == "publisher", me.text)
        check("1b: no token -> 401", (await client.get("/api/v1/auth/me")).status_code == 401)
        check("1c: publisher blocked from admin campaigns (403)",
              (await client.get("/api/v1/admin/campaigns", headers=pub1)).status_code == 403)
        check("1d: manager blocked from super-admin security overview (403)",
              (await client.get("/api/v1/admin/security/overview", headers=mgr1)).status_code == 403)

        # ---- 2. manager -> publisher scoping ----
        now = datetime.now(timezone.utc)
        ids = {}
        for key, h in (("m1", mgr1), ("m2", mgr2), ("p1", pub1), ("p2", pub2)):
            ids[key] = (await client.get("/api/v1/auth/me", headers=h)).json()["user_id"]
        await db["managers"].insert_one({"manager_id": "AM14001", "user_id": ids["m1"], "display_name": "M1", "created_at": now, "updated_at": now})
        await db["managers"].insert_one({"manager_id": "AM14002", "user_id": ids["m2"], "display_name": "M2", "created_at": now, "updated_at": now})
        await db["publishers"].insert_one({"publisher_id": "14001", "user_id": ids["p1"], "manager_id": "AM14001", "display_name": "P1", "created_at": now, "updated_at": now})
        await db["publishers"].insert_one({"publisher_id": "14002", "user_id": ids["p2"], "manager_id": "AM14002", "display_name": "P2", "created_at": now, "updated_at": now})

        await client.put("/api/v1/admin/settings/tracking-domain", headers=sa, json={"tracking_base_url": "https://track.example"})
        r = await client.post("/api/v1/admin/campaigns", headers=sa, json={
            "name": "P14 Campaign", "advertiser_name": "Acme",
            "advertiser_tracking_url": "https://adv.example/l?cid={click_id}",
            "platform": "Direct", "postback_platform": "custom",
            "postback_config": {"endpoint": "https://adv.example/pb"},
            "payout_min": 10, "payout_max": 200,
            "events": [{"event_name": "Install", "payout": 60, "completion_source": "online"}],
        })
        camp = r.json()["campaign_id"]
        await client.post(f"/api/v1/admin/campaigns/{camp}/activate", headers=sa)

        r = await client.post("/api/v1/links", headers=mgr1, json={"campaign_id": camp, "publisher_id": "14001"})
        check("2a: manager can create a link for OWN publisher", r.status_code in (200, 201), r.text)
        r = await client.post("/api/v1/links", headers=mgr1, json={"campaign_id": camp, "publisher_id": "14002"})
        check("2b: manager cannot create a link for ANOTHER manager's publisher", r.status_code in (403, 404), r.text)
        r = await client.get("/api/v1/links", headers=mgr2)
        check("2c: other manager's link list excludes P1's links",
              r.status_code == 200 and all(l.get("publisher_id") != "14001" for l in r.json()), r.text[:200])

        # ---- 3. publisher -> campaign application ----
        r = await client.get("/api/v1/campaign-access/available", headers=pub1)
        check("3a: publisher can browse available campaigns", r.status_code == 200, r.text[:200])
        check("3b: manager cannot use the publisher browse endpoint",
              (await client.get("/api/v1/campaign-access/available", headers=mgr1)).status_code == 403)
        r = await client.post(f"/api/v1/campaign-access/{camp}/access", headers=pub1)
        check("3c: publisher access request accepted", r.status_code in (200, 201), r.text[:200])

        # ---- 4. tracking -> click ----
        link = (await client.post("/api/v1/links", headers=sa, json={"campaign_id": camp, "publisher_id": "14001"})).json()
        r = await client.get(f"/api/v1/t/{link['campaign_code']}/{link['public_code']}?p1=abc", follow_redirects=False)
        check("4a: tracking link redirects (302)", r.status_code == 302, r.text[:200])
        qx = r.headers["location"].split("cid=")[1].split("&")[0]
        click = await db["clicks"].find_one({"digisnr_click_id": qx})
        check("4b: click stored with server-assigned publisher", click is not None and click["publisher_id"] == "14001")

        # ---- 5/8. click -> conversion via postback; webhook delivery ----
        wh = (await client.post("/api/v1/admin/integrations/webhooks", headers=sa,
                                json={"name": "P14", "url": "https://siem.example/hook", "events": ["conversion.created"]})).json()
        ep = (await client.post("/api/v1/admin/postback/endpoints", headers=sa, json={"campaign_id": camp, "platform": "offer18"})).json()
        tok = ep["inbound_url"].rstrip("/").split("/")[-1]
        url = f"/api/v1/postback/inbound/offer18/{tok}?aff_click_id={qx}&event_token=Install&payout=9999&transaction_id=P14T1"
        r = await client.get(url)
        check("5a: postback accepted", r.status_code == 200 and r.json()["status"] == "ok", r.text)
        conv = await db["conversions"].find_one({"digisnr_click_id": qx})
        check("5b: conversion payout comes from campaign config, not the postback", conv is not None and conv["payout"] == 60)
        await client.get(url)
        check("5c: duplicate postback creates no second conversion",
              await db["conversions"].count_documents({"digisnr_click_id": qx}) == 1)
        check("8a: webhook delivered once, HMAC verifiable",
              len(captured) == 1 and captured[0]["signature"] == webhook_service.sign_payload(wh["secret"], captured[0]["payload"]))
        d = await db["webhook_deliveries"].find_one({})
        check("8b: delivery logged as delivered", d is not None and d["final_status"] == "delivered")
        bad = await client.get(f"/api/v1/postback/inbound/offer18/not-a-token?aff_click_id={qx}&event_token=Install")
        check("8c: unknown postback token rejected", bad.status_code in (401, 403, 404), bad.text[:200])

        # ---- 6. conversion -> idempotent earning (Mongo-visible part) ----
        check("6a: conversion carries an approval_status",
              conv.get("approval_status") in ("confirmed", "pending_report"), str(conv.get("approval_status")))

        # ---- 9. earning -> withdrawal (needs Postgres) ----
        dsn = os.environ.get("POSTGRES_DSN", "")
        if "localhost" in dsn or "127.0.0.1" in dsn:
            r = await client.get("/api/v1/wallet/summary", headers=pub1)
            check("9a: wallet summary reachable with Postgres", r.status_code == 200, r.text[:200])
        else:
            skip("9: earning -> withdrawal lifecycle", "POSTGRES_DSN not set to a local Postgres; covered by part9_financial_test.py")

        # ---- 10. revoked session -> rejected ----
        r = await client.post("/api/v1/auth/logout", json={"refresh_token": pub1_refresh})
        check("10a: logout succeeds", r.status_code in (200, 204), r.text[:200])
        r = await client.get("/api/v1/auth/me", headers=pub1)
        check("10b: access token rejected immediately after its session is revoked", r.status_code == 401, r.text[:200])

    failed = [x for x in results if x[1] == "FAIL"]
    skipped = [x for x in results if x[1] == "SKIP"]
    print(f"\n{len(results) - len(failed) - len(skipped)} passed, {len(failed)} failed, {len(skipped)} skipped")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
