"""
Part 10 test suite — API keys (hash-only storage, scope enforcement, instant
revocation) + webhooks (HMAC signing, retries, replay, SSRF validation) +
the machine API. Run with: python3 tests/part10_integrations_test.py
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
    mongodb_module._db = mock_client["quantix_test_integrations"]
    await mongodb_module.ensure_indexes(mongodb_module._db)
    db = mongodb_module._db

    from httpx import AsyncClient, ASGITransport
    from app.main import create_app
    from app.services import postback_service, webhook_service

    async def fake_http_get(url):
        return 200, "OK", None

    postback_service._http_get = fake_http_get

    captured: list[dict] = []

    async def fake_http_post(url, payload, signature):
        captured.append({"url": url, "payload": payload, "signature": signature})
        return 200, "OK"

    webhook_service._http_post = fake_http_post

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async def token(email, role):
            r = await client.post("/api/v1/auth/_dev/issue-token", params={"email": email, "role": role})
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        sa = await token("superadmin@example.com", "super_admin")
        mgr = await token("manager1@example.com", "manager")
        pub = await token("pub1@example.com", "publisher")

        # ---------- API keys ----------
        r = await client.post("/api/v1/admin/integrations/api-keys", headers=sa,
                              json={"name": "Reporting CI", "scope": "reports:read"})
        key = r.json()
        check("X1: API key created, raw key shown once with DGK_ prefix",
              r.status_code == 200 and key["api_key"].startswith("DGK_"), r.text)
        stored = await db["api_keys"].find_one({"key_id": key["key_id"]})
        check("X2: only the SHA-256 hash is stored — raw key absent from DB",
              stored is not None and "api_key" not in stored and stored["key_hash"] != key["api_key"])
        r = await client.get("/api/v1/admin/integrations/api-keys", headers=sa)
        check("X3: key list shows prefix, never raw key",
              r.json()[0]["prefix"] == key["api_key"][:10] and "api_key" not in r.json()[0])
        check("X4: invalid scope rejected (422)",
              (await client.post("/api/v1/admin/integrations/api-keys", headers=sa,
                                 json={"name": "bad", "scope": "admin:all"})).status_code == 422)
        check("X5: manager/publisher cannot manage API keys (403)",
              (await client.post("/api/v1/admin/integrations/api-keys", headers=mgr,
                                 json={"name": "x", "scope": "reports:read"})).status_code == 403
              and (await client.get("/api/v1/admin/integrations/api-keys", headers=pub)).status_code == 403)

        # ---------- machine API ----------
        check("X6: machine API requires key (401)",
              (await client.get("/api/v1/api/reports/summary")).status_code == 401)
        check("X7: wrong key rejected (401)",
              (await client.get("/api/v1/api/reports/summary", headers={"X-API-Key": "DGK_wrong"})).status_code == 401)
        r = await client.get("/api/v1/api/reports/summary", headers={"X-API-Key": key["api_key"]})
        check("X8: valid key gets the report (200)", r.status_code == 200 and "totals" in r.json())
        await client.post(f"/api/v1/admin/integrations/api-keys/{key['key_id']}/revoke", headers=sa)
        check("X9: revoked key dies immediately (401)",
              (await client.get("/api/v1/api/reports/summary", headers={"X-API-Key": key["api_key"]})).status_code == 401)
        check("X10: create + revoke audited",
              await db["audit_logs"].find_one({"action": "API_KEY_CREATED"}) is not None
              and await db["audit_logs"].find_one({"action": "API_KEY_REVOKED"}) is not None)

        # ---------- webhooks ----------
        r = await client.post("/api/v1/admin/integrations/webhooks", headers=sa,
                              json={"name": "SIEM", "url": "https://siem.example/hook", "events": ["conversion.created"]})
        wh = r.json()
        check("W1: webhook created with signing secret (shown once)",
              r.status_code == 200 and wh["secret"].startswith("whsec_"), r.text)
        r = await client.get("/api/v1/admin/integrations/webhooks", headers=sa)
        check("W2: webhook list never exposes the secret", "secret" not in r.json()[0])
        check("W3: SSRF — localhost webhook URL rejected (422)",
              (await client.post("/api/v1/admin/integrations/webhooks", headers=sa,
                                 json={"name": "x", "url": "http://localhost:9000/hook", "events": ["conversion.created"]})).status_code == 422)
        check("W4: unsupported event rejected (422)",
              (await client.post("/api/v1/admin/integrations/webhooks", headers=sa,
                                 json={"name": "x", "url": "https://ok.example/h", "events": ["everything.now"]})).status_code == 422)

        # ---------- conversion triggers signed webhook ----------
        now = datetime.now(timezone.utc)
        mgr_uid = (await client.get("/api/v1/auth/me", headers=mgr)).json()["user_id"]
        pub_uid = (await client.get("/api/v1/auth/me", headers=pub)).json()["user_id"]
        await db["managers"].insert_one({"manager_id": "AM10001", "user_id": mgr_uid, "display_name": "Mgr One", "created_at": now, "updated_at": now})
        await db["publishers"].insert_one({"publisher_id": "1001", "user_id": pub_uid, "manager_id": "AM10001", "display_name": "Pub A", "created_at": now, "updated_at": now})
        await client.put("/api/v1/admin/settings/tracking-domain", headers=sa, json={"tracking_base_url": "https://track.example"})
        resp = await client.post("/api/v1/admin/campaigns", headers=sa, json={
            "name": "Hook Campaign", "advertiser_name": "Acme",
            "advertiser_tracking_url": "https://adv.example/l?cid={click_id}",
            "platform": "Direct", "postback_platform": "custom",
            "postback_config": {"endpoint": "https://adv.example/pb"},
            "payout_min": 10, "payout_max": 200,
            "events": [{"event_name": "Install", "payout": 60, "completion_source": "online"}],
        })
        camp = resp.json()["campaign_id"]
        await client.post(f"/api/v1/admin/campaigns/{camp}/activate", headers=sa)
        link = (await client.post("/api/v1/links", headers=sa, json={"campaign_id": camp, "publisher_id": "1001"})).json()
        r = await client.get(f"/api/v1/t/{link['campaign_code']}/{link['public_code']}", follow_redirects=False)
        qx = r.headers["location"].split("cid=")[1].split("&")[0]
        ep = (await client.post("/api/v1/admin/postback/endpoints", headers=sa, json={"campaign_id": camp, "platform": "offer18"})).json()
        ep_tok = ep["inbound_url"].rstrip("/").split("/")[-1]
        await client.get(f"/api/v1/postback/inbound/offer18/{ep_tok}?aff_click_id={qx}&event_token=Install&transaction_id=WH1")

        check("W5: conversion triggered exactly one signed webhook delivery",
              len(captured) == 1 and captured[0]["payload"]["event"] == "conversion.created"
              and captured[0]["payload"]["conversion_id"].startswith("QXCNV_"), str(len(captured)))
        expected_sig = webhook_service.sign_payload(wh["secret"], captured[0]["payload"])
        check("W6: X-DigiSNR-Signature is a verifiable HMAC of the payload",
              captured[0]["signature"] == expected_sig)
        delivery = await db["webhook_deliveries"].find_one({})
        check("W7: delivery logged with attempts + delivered status",
              delivery is not None and delivery["final_status"] == "delivered" and delivery["attempt_count"] == 1)

        # disabled webhook stays silent
        await client.post(f"/api/v1/admin/integrations/webhooks/{wh['webhook_id']}/disable", headers=sa)
        click2 = await client.get(f"/api/v1/t/{link['campaign_code']}/{link['public_code']}", follow_redirects=False)
        qx2 = click2.headers["location"].split("cid=")[1].split("&")[0]
        await client.get(f"/api/v1/postback/inbound/offer18/{ep_tok}?aff_click_id={qx2}&event_token=Install&transaction_id=WH2")
        check("W8: disabled webhook receives nothing", len(captured) == 1)

        # failed delivery retries to 4, then replay succeeds
        async def failing_post(url, payload, signature):
            return None, "connection refused"

        webhook_service._http_post = failing_post
        await client.post(f"/api/v1/admin/integrations/webhooks/{wh['webhook_id']}/enable", headers=sa)
        click3 = await client.get(f"/api/v1/t/{link['campaign_code']}/{link['public_code']}", follow_redirects=False)
        qx3 = click3.headers["location"].split("cid=")[1].split("&")[0]
        await client.get(f"/api/v1/postback/inbound/offer18/{ep_tok}?aff_click_id={qx3}&event_token=Install&transaction_id=WH3")
        failed = await db["webhook_deliveries"].find_one({"final_status": "failed"})
        check("W9: failed webhook retries to 4 attempts total",
              failed is not None and failed["attempt_count"] == 4)

        webhook_service._http_post = fake_http_post
        r = await client.post(f"/api/v1/admin/integrations/webhook-deliveries/{failed['delivery_id']}/replay", headers=sa)
        check("W10: manual replay delivers + audited",
              r.status_code == 200 and r.json()["final_status"] == "delivered" and r.json()["attempt_count"] == 5
              and await db["audit_logs"].find_one({"action": "WEBHOOK_REPLAYED"}) is not None)
        check("W11: manager cannot replay webhooks (403)",
              (await client.post(f"/api/v1/admin/integrations/webhook-deliveries/{failed['delivery_id']}/replay", headers=mgr)).status_code == 403)
        r = await client.get("/api/v1/admin/integrations/webhook-deliveries", headers=sa)
        check("W12: deliveries list works", r.status_code == 200 and len(r.json()) == 2)

    passed = sum(1 for _, s, _ in results if s == "PASS")
    print(f"\n--- SUMMARY ---\n{passed}/{len(results)} checks passed")
    return passed == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
