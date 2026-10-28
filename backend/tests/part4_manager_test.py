"""
Part 4 test suite — Manager panel: scoped dashboard, manager identity,
read-only campaign visibility, and re-verification that the locked Part 2
scope-isolation (publishers, invites, approvals) holds for the manager role.
Run with: python3 tests/part4_manager_test.py
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
    "name": "Net Offer",
    "advertiser_name": "Acme Corp",
    "advertiser_tracking_url": "https://acme.example/track",
    "platform": "Direct",
    "postback_platform": "custom",
    "postback_config": {"endpoint": "https://acme.example/pb"},
    "payout_min": 10,
    "payout_max": 100,
    "events": [{"event_name": "Install", "payout": 50, "completion_source": "online"}],
}


async def main():
    from bson import ObjectId
    from mongomock_motor import AsyncMongoMockClient
    import app.db.mongodb as mongodb_module

    mock_client = AsyncMongoMockClient()
    mongodb_module._client = mock_client
    mongodb_module._db = mock_client["quantix_test_manager"]
    await mongodb_module.ensure_indexes(mongodb_module._db)
    db = mongodb_module._db

    from httpx import AsyncClient, ASGITransport
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async def token(email, role):
            r = await client.post("/api/v1/auth/_dev/issue-token", params={"email": email, "role": role})
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        sa = await token("superadmin@example.com", "super_admin")
        mgr1 = await token("manager1@example.com", "manager")
        mgr2 = await token("manager2@example.com", "manager")
        pub = await token("publisher1@example.com", "publisher")

        # Resolve the dev users' ids and give managers their profiles.
        mgr1_id = (await client.get("/api/v1/auth/me", headers=mgr1)).json()["user_id"]
        mgr2_id = (await client.get("/api/v1/auth/me", headers=mgr2)).json()["user_id"]
        now = datetime.now(timezone.utc)
        await db["managers"].insert_one({"manager_id": "AM10001", "user_id": mgr1_id, "display_name": "Mgr One", "created_at": now, "updated_at": now})
        await db["managers"].insert_one({"manager_id": "AM10002", "user_id": mgr2_id, "display_name": "Mgr Two", "created_at": now, "updated_at": now})

        async def make_publisher(email, status, manager_id, pid):
            uid = str(ObjectId())
            await db["users"].insert_one({
                "_id": ObjectId(uid), "email": email, "password_hash": "x", "role": "publisher",
                "account_status": status, "email_verified": True, "created_at": now, "updated_at": now,
            })
            await db["publishers"].insert_one({
                "publisher_id": pid, "user_id": uid, "manager_id": manager_id,
                "display_name": email.split("@")[0], "created_at": now, "updated_at": now,
            })
            return uid

        await make_publisher("p1@example.com", "active", "AM10001", "1001")
        await make_publisher("p2@example.com", "pending", "AM10001", "1002")
        pub_of_mgr2 = await make_publisher("p3@example.com", "pending", "AM10002", "1003")

        # --- identity & role gating ---
        r = await client.get("/api/v1/manager/me", headers=mgr1)
        check("M1: manager identity resolves (manager_id + display_name)",
              r.status_code == 200 and r.json()["manager_id"] == "AM10001" and r.json()["display_name"] == "Mgr One", r.text)
        check("M2: publisher rejected from manager panel (403)",
              (await client.get("/api/v1/manager/me", headers=pub)).status_code == 403)
        check("M3: super admin rejected from manager panel (403 — separate panel)",
              (await client.get("/api/v1/manager/dashboard", headers=sa)).status_code == 403)
        check("M4: unauthenticated rejected (401)",
              (await client.get("/api/v1/manager/dashboard")).status_code == 401)

        # --- scoped dashboard ---
        r = await client.get("/api/v1/manager/dashboard", headers=mgr1)
        d = r.json()
        check("M5: dashboard counts only own publishers (total=2, active=1, pending=1)",
              d["publishers"] == {"total": 2, "active": 1, "pending": 1, "rejected": 0}, str(d["publishers"]))
        r2 = await client.get("/api/v1/manager/dashboard", headers=mgr2)
        check("M6: second manager sees only own scope (total=1)",
              r2.json()["publishers"]["total"] == 1, str(r2.json()["publishers"]))
        check("M7: tracking KPIs are honest unavailable, never fabricated",
              d["clicks"]["available"] is False and d["clicks"]["value"] is None)

        # --- campaigns: active-only visibility ---
        async def make_campaign(name, activate=False, pause=False):
            resp = await client.post("/api/v1/admin/campaigns", headers=sa, json={**BASE_CAMPAIGN, "name": name})
            cid = resp.json()["campaign_id"]
            if activate:
                await client.post(f"/api/v1/admin/campaigns/{cid}/activate", headers=sa)
            if pause:
                await client.post(f"/api/v1/admin/campaigns/{cid}/pause", headers=sa, json={"reason": "hold"})
            return cid

        draft_id = await make_campaign("Draft Offer")
        active_id = await make_campaign("Live Offer", activate=True)
        await make_campaign("Paused Offer", activate=True, pause=True)

        r = await client.get("/api/v1/manager/campaigns", headers=mgr1)
        names = [c["name"] for c in r.json()]
        check("M8: manager sees only ACTIVE campaigns",
              names == ["Live Offer"], str(names))

        r = await client.get(f"/api/v1/manager/campaigns/{active_id}", headers=mgr1)
        body = r.json()
        check("M9: manager campaign detail has events + payouts (advertiser rates permitted, spec §6)",
              r.status_code == 200 and body["events"][0]["payout"] == 50)
        check("M10: advertiser tracking URL is NOT exposed to manager projection",
              "advertiser_tracking_url" not in body and "postback_config" not in body)

        check("M11: draft campaign is invisible to manager (404, no existence leak)",
              (await client.get(f"/api/v1/manager/campaigns/{draft_id}", headers=mgr1)).status_code == 404)
        check("M12: unknown campaign -> 404",
              (await client.get("/api/v1/manager/campaigns/CAMPXXXX", headers=mgr1)).status_code == 404)

        d2 = (await client.get("/api/v1/manager/dashboard", headers=mgr1)).json()
        check("M13: dashboard available_campaigns reflects active network campaigns",
              d2["available_campaigns"] == 1, str(d2["available_campaigns"]))

        # --- locked Part 2 scope isolation still holds for managers ---
        r = await client.get("/api/v1/publishers", headers=mgr1)
        pids = [p["publisher_id"] for p in r.json()]
        check("M14: GET /publishers stays manager-scoped (1001,1002 only)",
              sorted(pids) == ["1001", "1002"], str(pids))

        r = await client.post(f"/api/v1/publishers/{pub_of_mgr2}/approve", headers=mgr1)
        check("M15: manager cannot approve another manager's publisher (403)", r.status_code == 403)

        r = await client.post(f"/api/v1/publishers/{pub_of_mgr2}/approve", headers=mgr2)
        check("M16: owning manager can approve own pending publisher",
              r.status_code == 200 and r.json()["account_status"] == "active", r.text)

        r = await client.post("/api/v1/invites/publisher", headers=mgr1,
                              json={"target_email": "newpub@example.com", "manager_id": "AM10002"})
        check("M17: manager-created publisher invite is force-bound to OWN manager_id (body value ignored)",
              r.status_code == 200 and r.json()["manager_id"] == "AM10001", r.text)

        r = await client.get("/api/v1/admin/managers", headers=mgr1)
        check("M18: manager cannot reach super-admin endpoints (403)", r.status_code == 403)

    passed = sum(1 for _, s, _ in results if s == "PASS")
    print(f"\n--- SUMMARY ---\n{passed}/{len(results)} checks passed")
    return passed == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
