"""Publisher panel endpoints (Part 7, spec §52) — PUBLISHER role, own data
only. The projection here is the security boundary: advertiser revenue,
upstream payout, margin, and other publishers' data are never selected,
so they can never leak (spec §52)."""
import re
import asyncio
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from pydantic import BaseModel, Field

from app.core.enums import Role
from app.core.exceptions import NotFoundError
from app.core.rbac import CurrentUser, require_role
from app.db import (
    campaign_access_repository, campaign_repository, conversion_repository, manager_repository,
    publisher_repository, tracking_repository, user_repository,
)
from app.services import postback_service
from app.services import publisher_report_service as prs
from app.services import settings_service

router = APIRouter()

_publisher_only = require_role(Role.PUBLISHER)


async def _profile(user: CurrentUser) -> dict:
    profile = await publisher_repository.get_publisher_by_user_id(user.user_id)
    if profile is None:
        raise NotFoundError("Publisher profile not found for current user")
    return profile


@router.get("/dashboard")
async def publisher_dashboard(user: CurrentUser = Depends(_publisher_only)):
    profile = await _profile(user)
    publisher_id = profile["publisher_id"]
    # Independent reads run concurrently (previously one after another: each is a
    # storage round trip, which is what made the dashboard take many seconds).
    stats, clicks, conversions, earnings, links, recent = await asyncio.gather(
        conversion_repository.publisher_dashboard_stats(publisher_id),
        tracking_repository.count_clicks_for_publisher(publisher_id),
        conversion_repository.count_conversions_for_publisher(publisher_id),
        conversion_repository.sum_earnings_for_publisher(publisher_id),
        tracking_repository.list_links(publisher_id=publisher_id),
        publisher_conversions(
            user=user, page=1, page_size=5, _profile_doc=profile,
            campaign_id=None, date_from=None, date_to=None, approval_status=None, search=None,
        ),
    )
    top = stats["top_campaigns"]
    campaigns = await asyncio.gather(*[campaign_repository.get_campaign(t["campaign_id"]) for t in top])
    for t, c in zip(top, campaigns):
        t["name"] = c["summary"]["name"] if c else t["campaign_id"]
    return {
        "publisher_id": publisher_id,
        "public_code": profile.get("public_code"),
        "display_name": profile["display_name"],
        "clicks": clicks,
        "conversions": conversions,
        "earnings": earnings,
        "links": len(links),
        "stats": stats,
        "recent_conversions": recent,
    }


@router.get("/campaigns")
async def publisher_campaigns(user: CurrentUser = Depends(_publisher_only)):
    """Campaigns the publisher holds a tracking link for — with THEIR payout
    per event (the configured publisher payout, spec §14/§52)."""
    profile = await _profile(user)
    links = await tracking_repository.list_links(publisher_id=profile["publisher_id"])
    out = []
    for link in links:
        campaign = await campaign_repository.get_campaign(link["campaign_id"])
        # Paused / ended / purged campaigns disappear from Approved Campaigns and come back when Active again.
        if campaign is None or campaign["status"] != "active":
            continue
        config = await campaign_repository.get_current_config(campaign)
        out.append({
            "campaign_id": campaign["campaign_id"],
            "name": campaign["summary"]["name"],
            "status": campaign["status"],
            "tracking_url_path": f"{link['campaign_code']}/{link['public_code']}",
            "logo_url": (config or {}).get("logo_url"),
            "tracking_only": bool((config or {}).get("tracking_only")),
            "approval_mode": (config or {}).get("approval_mode") or "promote_immediately",
            "events": [
                {"event_name": e["event_name"], "payout": e["payout"], "completion_source": e["completion_source"]}
                for e in (config or {}).get("events", [])
            ],
        })
    return out


@router.get("/clicks")
async def publisher_clicks(
    user: CurrentUser = Depends(_publisher_only),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    campaign_id: str | None = Query(default=None, max_length=40),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = Query(default=None, max_length=64),
):
    profile = await _profile(user)
    docs = await tracking_repository.list_clicks_filtered(
        profile["publisher_id"], (page - 1) * page_size, page_size, campaign_id, date_from, date_to, search
    )
    names = await prs.campaign_name_map(profile["publisher_id"])
    # Publisher-facing: no device/OS/browser. Values not captured stay null.
    return [prs.click_row(c, names) for c in docs]


@router.get("/conversions")
async def publisher_conversions(
    user: CurrentUser = Depends(_publisher_only),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _profile_doc: dict | None = None,
    campaign_id: str | None = Query(default=None, max_length=40),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    approval_status: str | None = Query(default=None, pattern="^(pending_report|confirmed|rejected)$"),
    search: str | None = Query(default=None, max_length=64),
):
    """Conversion report: ONE row per DigiSNR click ID. Each event (Install,
    Register, KYC, ...) is a badge with its payout on that click's row; the row
    date stays the original click date. Publisher-safe projection — payout is
    what THEY earn; advertiser revenue/upstream payout/margin are absent (spec §52)."""
    profile = _profile_doc or await _profile(user)
    docs = await conversion_repository.list_conversions_filtered(
        profile["publisher_id"], 0, prs.GROUP_FETCH_CAP,
        campaign_id, date_from, date_to, approval_status, search,
    )
    names = await prs.campaign_name_map(profile["publisher_id"])
    clicks = await prs.clicks_by_ids([c["digisnr_click_id"] for c in docs])
    groups = prs.grouped_conversion_rows(docs, clicks, names)
    start = (page - 1) * page_size
    return groups[start:start + page_size]


@router.get("/conversions/event-summary")
async def publisher_event_summary(
    user: CurrentUser = Depends(_publisher_only),
    campaign_id: str | None = Query(default=None, max_length=40),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    """Per-event conversion count + payout from real conversion records."""
    profile = await _profile(user)
    return await prs.event_summary(profile["publisher_id"], campaign_id, date_from, date_to)


# ---------- Export Center (background jobs, own data only) ----------

class ExportRequest(BaseModel):
    kind: str = Field(pattern="^(clicks|conversions)$")
    format: str = Field(default="csv", pattern="^(csv|json)$")
    campaign_id: str | None = Field(default=None, max_length=40)
    date_from: str | None = Field(default=None, max_length=40)
    date_to: str | None = Field(default=None, max_length=40)
    unique_ip: bool = False


@router.post("/exports")
async def request_export(body: ExportRequest, background: BackgroundTasks, user: CurrentUser = Depends(_publisher_only)):
    profile = await _profile(user)
    job = await prs.create_export_job(
        profile["publisher_id"], user.user_id, body.kind, body.format,
        body.campaign_id, body.date_from, body.date_to, body.unique_ip,
    )
    background.add_task(prs.run_export_job, job["job_id"])
    return prs.serialize_job(job)


@router.get("/exports")
async def list_exports(kind: str | None = Query(default=None, pattern="^(clicks|conversions)$"),
                       user: CurrentUser = Depends(_publisher_only)):
    profile = await _profile(user)
    return await prs.list_jobs(profile["publisher_id"], kind)


@router.get("/exports/{job_id}/download")
async def download_export(job_id: str, user: CurrentUser = Depends(_publisher_only)):
    profile = await _profile(user)
    job, content = await prs.get_job_content(profile["publisher_id"], job_id)
    is_json = job["format"] == "json"
    return Response(
        content,
        media_type="application/json" if is_json else "text/csv",
        headers={"Content-Disposition": f'attachment; filename="digisnr-{job["kind"]}-{job_id}.{ "json" if is_json else "csv"}"'},
    )


@router.get("/postback-logs")
async def publisher_postback_logs(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
    campaign_id: str | None = Query(default=None, max_length=40),
    user: CurrentUser = Depends(_publisher_only),
):
    """Own outbound postback deliveries only — publisher_id is server-pinned,
    never taken from the request (spec §52)."""
    profile = await _profile(user)
    items, total = await conversion_repository.list_outbound(
        publisher_id=profile["publisher_id"], campaign_id=campaign_id, skip=(page - 1) * page_size, limit=page_size,
    )
    return {
        "items": [
            {
                "outbound_id": o["outbound_id"], "conversion_id": o["conversion_id"],
                "campaign_id": o["campaign_id"], "event": o.get("event"),
                "direction": "outbound",
                "url": postback_service.safe_url(o.get("url")),
                # Full URL for the publisher's OWN delivery (their configured postback). Shown only in the View popup.
                "full_url": o.get("url"),
                "attempt_count": o.get("attempt_count", 0), "final_status": o["final_status"],
                "retries": max(0, o.get("attempt_count", 0) - 1),
                "created_at": o["created_at"],
                "http_status": (o.get("attempts") or [{}])[-1].get("http_status"),
                "latency_ms": (o.get("attempts") or [{}])[-1].get("latency_ms"),
                "last_error": (o.get("attempts") or [{}])[-1].get("error"),
            }
            for o in items
        ],
        "total": total,
    }


def _ua_os(ua: str | None) -> str:
    u = (ua or "").lower()
    for key, label in (("windows", "Windows"), ("android", "Android"), ("iphone", "iOS"), ("ipad", "iOS"),
                       ("mac os", "macOS"), ("linux", "Linux")):
        if key in u:
            return label
    return "Unknown"


def _ua_browser(ua: str | None) -> str:
    u = (ua or "").lower()
    for key, label in (("edg/", "Edge"), ("opr/", "Opera"), ("samsungbrowser", "Samsung Browser"),
                       ("chrome", "Chrome"), ("firefox", "Firefox"), ("safari", "Safari")):
        if key in u:
            return label
    return "Unknown"


def _tally(values: list[str], n: int = 6) -> list[dict]:
    return [{"label": k, "count": v} for k, v in Counter(values).most_common(n)]


@router.get("/campaigns/{campaign_id}")
async def publisher_campaign_detail(campaign_id: str, user: CurrentUser = Depends(_publisher_only)):
    """Publisher-safe campaign page. Whitelisted fields only: no advertiser
    URL, no upstream postback config, no revenue/margin (spec §52)."""
    profile = await _profile(user)
    publisher_id = profile["publisher_id"]
    campaign = await campaign_repository.get_campaign(campaign_id)
    if campaign is None or campaign["status"] not in ("active", "paused"):
        raise NotFoundError("Campaign not found")
    cfg = await campaign_repository.get_current_config(campaign) or {}
    access = await campaign_access_repository.get(campaign_id, publisher_id)
    link = await tracking_repository.find_active_link(campaign_id, publisher_id)
    tracking_url = None
    if link:
        base = await settings_service.get_active_tracking_base_url()
        tracking_url = (
            settings_service.build_tracking_url_from_base(base, link["campaign_code"], link["public_code"]) if base else None
        )
    clicks = await tracking_repository.clicks_for_campaign(publisher_id, campaign_id)
    events = [
        {"event_name": e["event_name"], "payout": e["payout"], "completion_source": e["completion_source"]}
        for e in cfg.get("events", [])
    ]
    postback = await conversion_repository.get_postback_config(publisher_id, campaign_id)
    logs, _ = await conversion_repository.list_outbound(publisher_id=publisher_id, campaign_id=campaign_id, skip=0, limit=10)
    return {
        "campaign_id": campaign_id,
        "name": campaign["summary"]["name"],
        "status": campaign["status"],
        "logo_url": cfg.get("logo_url"),
        "description": cfg.get("description"),
        "category": cfg.get("category"),
        "kind": cfg.get("kind") or "standard",
        "tracking_only": bool(cfg.get("tracking_only")),
        "countries": cfg.get("countries") or [],
        "approval_mode": cfg.get("approval_mode") or "promote_immediately",
        "tracking_window_hours": cfg.get("tracking_window_hours"),
        # Which of the publisher's P1–P10 slots DigiSanchaar uses for its own click id
        # on this campaign (None when the carrier isn't a p-slot). Never the raw name.
        "reserved_slot": (int(str(cfg.get("click_id_param"))[1:]) if re.fullmatch(r"[pP](10|[1-9])", str(cfg.get("click_id_param") or "")) else None),
        "events": events,
        "max_payout": max((e["payout"] for e in events), default=None),
        "access_status": access["status"] if access else None,
        "tracking_url": tracking_url,
        "analytics": {
            "total_clicks": len(clicks),
            "countries": len({c.get("country") for c in clicks if c.get("country")}),
            "by_os": _tally([_ua_os(c.get("user_agent")) for c in clicks]),
            "by_browser": _tally([_ua_browser(c.get("user_agent")) for c in clicks]),
            "by_country": _tally([c.get("country") or "Unknown" for c in clicks]),
            "by_city": _tally([c.get("city") or "Unknown" for c in clicks]),
        },
        "postback": {"configured": postback is not None, "url_template": postback["url_template"] if postback else None,
                     "enabled": postback["enabled"] if postback else False},
        "postback_logs": [
            {"outbound_id": o["outbound_id"], "created_at": o["created_at"], "final_status": o["final_status"],
             "event": o.get("event"), "http_status": (o.get("attempts") or [{}])[-1].get("http_status"),
             "latency_ms": (o.get("attempts") or [{}])[-1].get("latency_ms")}
            for o in logs
        ],
    }


@router.get("/profile")
async def publisher_profile(user: CurrentUser = Depends(_publisher_only)):
    profile = await _profile(user)
    account = await user_repository.get_user_by_id(user.user_id)
    return {
        "publisher_id": profile["publisher_id"],
        "public_code": profile.get("public_code"),
        "display_name": profile["display_name"],
        "email": account.email if account else None,
        "email_verified": bool(account.email_verified) if account else False,
        "account_status": account.account_status.value if account else None,
        "mobile": profile.get("mobile"),
        "company": profile.get("company"),
        "member_since": profile.get("created_at"),
        # Safe projection only (name) - never the Manager's email/ids/internal data.
        "assigned_manager_name": await _assigned_manager_name(profile),
    }


async def _assigned_manager_name(profile: dict) -> str | None:
    if not profile.get("manager_id"):
        return None
    manager = await manager_repository.get_manager_by_manager_id(profile["manager_id"])
    return manager["display_name"] if manager else None


@router.get("/account-manager")
async def publisher_account_manager(user: CurrentUser = Depends(_publisher_only)):
    """Name of the publisher's own account manager (from their invite) — for
    the sidebar's Support & Help card. No other manager data is exposed."""
    profile = await _profile(user)
    manager = await manager_repository.get_manager_by_manager_id(profile["manager_id"]) if profile.get("manager_id") else None
    return {"name": manager["display_name"] if manager else None, "mobile": manager.get("mobile") if manager else None}
