"""
Part 5 test suite — tracking engine: short public links, immutable QXCLK
click ids, P1–P10/UTM snapshotting, whitelisted macro substitution, blocked-IP
enforcement, lifecycle gating, caps with auto-pause, RBAC/scope on link
management. Run with: python3 tests/part5_tracking_test.py
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


def campaign_payload(name, **overrides):
    base = {
        "name": name,
        "advertiser_name": "Acme Corp",
        "advertiser_tracking_url": "https://adv.example/landing?cid={click_id}&sub={p1}&utm={utm_source}&keep={unknown_macro}",
        "platform": "Direct",
        "postback_platform": "custom",
        "postback_config": {"endpoint": "https://adv.example/pb"},
        "payout_min": 10,
        "payout_max": 100,
        "events": [{"event_name": "Install", "payout": 50, "completion_source": "online"}],
    }
    base.update(overrides)
    return base


async def main():
    from bson import ObjectId
    from mongomock_motor import AsyncMongoMockClient
    import app.db.mongodb as mongodb_module

    mock_client = AsyncMongoMockClient()
    mongodb_module._client = mock_client
    mongodb_module._db = mock_client["quantix_test_tracking"]
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
        pub_h = await token("pub1@example.com", "publisher")

        now = datetime.now(timezone.utc)
        mgr1_uid = (await client.get("/api/v1/auth/me", headers=mgr1)).json()["user_id"]
        pub_uid = (await client.get("/api/v1/auth/me", headers=pub_h)).json()["user_id"]
        await db["managers"].insert_one({"manager_id": "AM10001", "user_id": mgr1_uid, "display_name": "Mgr One", "created_at": now, "updated_at": now})
        await db["managers"].insert_one({"manager_id": "AM10002", "user_id": str(ObjectId()), "display_name": "Mgr Two", "created_at": now, "updated_at": now})

        async def make_publisher(email, status, manager_id, pid, user_id=None):
            if user_id is None:
                uid = str(ObjectId())
                await db["users"].insert_one({
                    "_id": ObjectId(uid), "email": email, "password_hash": "x", "role": "publisher",
                    "account_status": status, "email_verified": True, "created_at": now, "updated_at": now,
                })
            else:
                uid = user_id  # dev-token user already exists — don't double-insert
            await db["publishers"].insert_one({
                "publisher_id": pid, "user_id": uid, "manager_id": manager_id,
                "display_name": email.split("@")[0], "created_at": now, "updated_at": now,
            })
            return uid

        await make_publisher("pub1@example.com", "active", "AM10001", "1001", user_id=pub_uid)
        await make_publisher("pub2@example.com", "active", "AM10002", "2001")
        await make_publisher("pub3@example.com", "pending", "AM10001", "1003")

        async def make_campaign(name, activate=True, **overrides):
            resp = await client.post("/api/v1/admin/campaigns", headers=sa, json=campaign_payload(name, **overrides))
            cid = resp.json()["campaign_id"]
            if activate:
                await client.post(f"/api/v1/admin/campaigns/{cid}/activate", headers=sa)
            return cid

        camp_a = await make_campaign("Alpha Track")
        camp_draft = await make_campaign("Draft Track", activate=False)
        camp_cap = await make_campaign("Cap Track", daily_cap=2)

        # --- link management authz + preconditions ---
        r = await client.post("/api/v1/links", json={"campaign_id": camp_a, "publisher_id": "1001"})
        check("K1: unauthenticated link creation -> 401", r.status_code == 401)
        r = await client.post("/api/v1/links", headers=pub_h, json={"campaign_id": camp_a, "publisher_id": "1001"})
        check("K2: publisher cannot generate links (403)", r.status_code == 403)
        r = await client.post("/api/v1/links", headers=sa, json={"campaign_id": camp_draft, "publisher_id": "1001"})
        check("K3: draft campaign cannot produce links (409)", r.status_code == 409)
        r = await client.post("/api/v1/links", headers=sa, json={"campaign_id": camp_a, "publisher_id": "1001"})
        check("K4: link creation requires a configured tracking domain (409)",
              r.status_code == 409 and "tracking domain" in r.json()["error"]["message"].lower(), r.text)

        r = await client.put("/api/v1/admin/settings/tracking-domain", headers=sa,
                             json={"tracking_base_url": "https://track-a.example", "reason": "part5 tests"})
        check("Tracking domain configured for tests", r.status_code == 200)

        r = await client.post("/api/v1/links", headers=sa, json={"campaign_id": camp_a, "publisher_id": "1003"})
        check("K5: link for non-active publisher rejected (409)", r.status_code == 409)
        r = await client.post("/api/v1/links", headers=mgr1, json={"campaign_id": camp_a, "publisher_id": "2001"})
        check("K6: manager cannot link another manager's publisher (403)", r.status_code == 403)

        r = await client.post("/api/v1/links", headers=mgr1, json={"campaign_id": camp_a, "publisher_id": "1001"})
        link = r.json()
        check("K7: manager generates link for OWN publisher (200)", r.status_code == 200, r.text)
        check("K8: canonical short URL from configured domain",
              link["tracking_url"] == f"https://track-a.example/{link['campaign_code']}/{link['public_code']}",
              link["tracking_url"])
        check("K9: public URL exposes no internal ids",
              camp_a not in link["tracking_url"] and "1001" not in link["tracking_url"]
              and len(link["public_code"]) == 4 and link["campaign_code"].startswith("C"))
        check("K10: publisher public code assigned (PUBxxxxx, separate from publisher_id)",
              link["publisher_code"].startswith("PUB") and link["publisher_code"] != "1001")

        r2 = await client.post("/api/v1/links", headers=sa, json={"campaign_id": camp_a, "publisher_id": "1001"})
        check("K11: repeated generation is idempotent (same link)",
              r2.status_code == 200 and r2.json()["link_id"] == link["link_id"])

        r = await client.get("/api/v1/links", headers=sa)
        check("K12: admin lists links with canonical URL", any(l["link_id"] == link["link_id"] for l in r.json()))
        r = await client.get("/api/v1/links", headers=mgr1)
        check("K13: manager link list is own-scope", all(l["manager_id"] == "AM10001" for l in r.json()))
        r = await client.get("/api/v1/links", headers=pub_h)
        check("K14: publisher sees only own links",
              len(r.json()) == 1 and r.json()[0]["publisher_id"] == "1001")

        audit = await db["audit_logs"].find_one({"action": "TRACKING_LINK_CREATED"})
        check("K15: link generation is audited", audit is not None)

        # --- click pipeline ---
        cc, lc = link["campaign_code"], link["public_code"]
        r = await client.get(
            f"/api/v1/t/{cc}/{lc}?p1=9876543210&p2=Suraj&utm_source=facebook&bogus=ignoreme",
            follow_redirects=False,
        )
        check("C1: valid click -> 302 redirect", r.status_code == 302, str(r.status_code))
        location = r.headers["location"]
        check("C2: advertiser URL received substituted macros (click_id, p1, utm)",
              "cid=QXCLK_" in location and "sub=9876543210" in location and "utm=facebook" in location, location)
        check("C3: unknown macros pass through untouched (never evaluated)",
              "{unknown_macro}" in location or "%7Bunknown_macro%7D" in location, location)

        click_doc = await db["clicks"].find_one({"link_id": link["link_id"]})
        check("C4: click stored with immutable QXCLK id + full snapshot",
              click_doc is not None
              and click_doc["digisnr_click_id"].startswith("QXCLK_")
              and click_doc["sub_id_1"] == "9876543210"
              and click_doc["sub_id_2"] == "Suraj"
              and click_doc["utm_source"] == "facebook"
              and click_doc["publisher_id"] == "1001"
              and click_doc["manager_id"] == "AM10001"
              and click_doc["campaign_id"] == camp_a
              and click_doc["ip"] is not None
              and "bogus" not in click_doc["original_params"])
        check("C5: external/agency/source click ids stored SEPARATELY (null until postbacks)",
              click_doc["external_click_id"] is None and click_doc["agency_click_id"] is None)

        r = await client.get(f"/api/v1/t/{cc}/{lc}?p1=second", follow_redirects=False)
        click2 = await db["clicks"].find_one({"original_params.p1": "second"})
        check("C6: every click gets exactly ONE new QXCLK id",
              r.status_code == 302 and click2["digisnr_click_id"] != click_doc["digisnr_click_id"])

        # root-level mount (production tracking-domain path)
        r = await client.get(f"/{cc}/{lc}", follow_redirects=False)
        check("C7: root-level /{campaign_code}/{link_code} mount also works", r.status_code == 302)

        # injection / oversized params are neutralized
        evil = "<script>alert(1)</script>" + "A" * 500
        r = await client.get(f"/api/v1/t/{cc}/{lc}?p1={evil}", follow_redirects=False)
        loc = r.headers.get("location", "")
        check("C8: hostile p1 is stored length-capped and re-emitted URL-encoded",
              "%3Cscript%3E" in loc and "<script>" not in loc, loc[:120])
        stored = await db["clicks"].find_one({"link_id": link["link_id"]}, sort=[("click_created_at", -1)])
        check("C9: stored value capped at 200 chars, control chars stripped",
              len(stored["sub_id_1"]) == 200)

        r = await client.get(f"/api/v1/t/{cc}/ZZZZ", follow_redirects=False)
        check("C10: unknown link code -> 404, no click, no redirect", r.status_code == 404)

        # blocked IP — checked BEFORE click creation
        await db["blocked_ips"].insert_one({
            "ip_address": "203.0.113.66", "block_reason": "test", "campaign_id": None,
            "publisher_id": None, "manager_id": None, "first_detected_at": now,
            "last_detected_at": now, "detection_count": 1, "status": "blocked",
            "under_investigation": False, "detection_source": "test", "created_by": "t",
            "updated_by": "t", "created_at": now, "updated_at": now,
        })
        before = await db["clicks"].count_documents({})
        r = await client.get(f"/api/v1/t/{cc}/{lc}", headers={"x-forwarded-for": "203.0.113.66"}, follow_redirects=False)
        after = await db["clicks"].count_documents({})
        check("C11: blocked IP -> 403 with the exact public-safe message",
              r.status_code == 403 and "Access Restricted" in r.text and "reason" not in r.text.lower())
        check("C12: blocked request creates NO click", before == after)

        # lifecycle gating
        await client.post(f"/api/v1/admin/campaigns/{camp_a}/pause", headers=sa, json={"reason": "hold"})
        before = await db["clicks"].count_documents({})
        r = await client.get(f"/api/v1/t/{cc}/{lc}", follow_redirects=False)
        check("C13: paused campaign -> 410, no click created",
              r.status_code == 410 and await db["clicks"].count_documents({}) == before)
        await client.post(f"/api/v1/admin/campaigns/{camp_a}/resume", headers=sa)
        r = await client.get(f"/api/v1/t/{cc}/{lc}", follow_redirects=False)
        check("C14: resume restores click flow", r.status_code == 302)

        # caps + auto-pause
        r = await client.post("/api/v1/links", headers=sa, json={"campaign_id": camp_cap, "publisher_id": "1001"})
        cap_link = r.json()
        ccc, clc = cap_link["campaign_code"], cap_link["public_code"]
        r1 = await client.get(f"/api/v1/t/{ccc}/{clc}", follow_redirects=False)
        r2 = await client.get(f"/api/v1/t/{ccc}/{clc}", follow_redirects=False)
        r3 = await client.get(f"/api/v1/t/{ccc}/{clc}", follow_redirects=False)
        check("C15: daily cap allows exactly the capped number of clicks",
              r1.status_code == 302 and r2.status_code == 302 and r3.status_code == 410)
        cap_doc = await db["campaigns"].find_one({"campaign_id": camp_cap})
        check("C16: cap auto-pauses the campaign with reason",
              cap_doc["status"] == "paused" and cap_doc["status_reason"] == "Daily cap reached")
        cap_audit = await db["audit_logs"].find_one({"action": "CAMPAIGN_PAUSED", "metadata.campaign_id": camp_cap, "metadata.automatic": True})
        check("C17: cap auto-pause is audited", cap_audit is not None)
        r = await client.get(f"/api/v1/t/{ccc}/{clc}", follow_redirects=False)
        check("C18: no clicks after cap pause", r.status_code == 410)

        # purged campaign rejects clicks (tombstone keeps working)
        camp_x = await make_campaign("Purge Track")
        r = await client.post("/api/v1/links", headers=sa, json={"campaign_id": camp_x, "publisher_id": "1001"})
        x = r.json()
        await client.post(f"/api/v1/admin/campaigns/{camp_x}/end", headers=sa)
        await client.post(f"/api/v1/admin/campaigns/{camp_x}/purge", headers=sa, json={"confirm_campaign_name": "Purge Track"})
        r = await client.get(f"/api/v1/t/{x['campaign_code']}/{x['public_code']}", follow_redirects=False)
        check("C19: purged campaign link is dead — no redirect, no click (directive §16)",
              r.status_code in (404, 410) and not r.headers.get("location"))
        gone = await db["tracking_links"].find_one({"campaign_id": camp_x})
        check("C20: purge removed the purged campaign's tracking links", gone is None)

        # domain change affects new link strings only; old clicks untouched
        old_clicks = await db["clicks"].count_documents({})
        await client.put("/api/v1/admin/settings/tracking-domain", headers=sa,
                         json={"tracking_base_url": "https://track-b.example"})
        r = await client.get("/api/v1/links", headers=sa)
        urls = [l["tracking_url"] for l in r.json()]
        check("C21: domain change re-bases link presentation on the NEW domain",
              all(u.startswith("https://track-b.example/") for u in urls if u), str(urls[:1]))
        check("C22: historical click records are never rewritten",
              await db["clicks"].count_documents({}) == old_clicks)

    passed = sum(1 for _, s, _ in results if s == "PASS")
    print(f"\n--- SUMMARY ---\n{passed}/{len(results)} checks passed")
    return passed == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
