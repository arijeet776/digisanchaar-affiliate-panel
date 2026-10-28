"""
Reporting service (Part 8, spec §38/§53). Aggregations are computed from real
click + conversion records only. Bounded scans (hard cap) keep memory flat;
the scale ceiling is documented, not hidden.
"""
import logging
from datetime import datetime, timezone

from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

MAX_REPORT_SCAN = 20000  # hard bound per report query (spec §68: safe limits)


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def build_report(
    *,
    date_from: str | None,
    date_to: str | None,
    campaign_id: str | None = None,
    manager_id: str | None = None,
    publisher_id: str | None = None,
    event: str | None = None,
    platform: str | None = None,
    status: str | None = None,
    group_by: str = "campaign",
) -> dict:
    """Totals + rows grouped by campaign|manager|publisher|event. Manager and
    publisher scoping is enforced by the CALLER passing the fixed scope value —
    the service never trusts a client to widen it."""
    db = get_database()
    dt_from, dt_to = _parse_dt(date_from), _parse_dt(date_to)

    click_q: dict = {}
    conv_q: dict = {}
    if campaign_id:
        click_q["campaign_id"] = conv_q["campaign_id"] = campaign_id
    if manager_id:
        click_q["manager_id"] = conv_q["manager_id"] = manager_id
    if publisher_id:
        click_q["publisher_id"] = conv_q["publisher_id"] = publisher_id
    if dt_from or dt_to:
        window = {}
        if dt_from:
            window["$gte"] = dt_from
        if dt_to:
            window["$lte"] = dt_to
        click_q["click_created_at"] = window
        conv_q["conversion_created_at"] = window

    click_counts: dict[str, int] = {}
    async def click_count(query) -> int:
        return await db["clicks"].count_documents(query)

    # Clicks per group key
    group_keys = {"campaign": "campaign_id", "manager": "manager_id", "publisher": "publisher_id", "event": "event"}
    gk = group_keys.get(group_by, "campaign_id")

    click_totals = await click_count(click_q)
    # per-group click counts (bounded scan)
    group_clicks: dict[str, int] = {}
    if gk != "event":
        docs = await db["clicks"].find(click_q, {gk: 1}).limit(MAX_REPORT_SCAN).to_list(length=MAX_REPORT_SCAN)
        for doc in docs:
            key = doc.get(gk) or "—"
            group_clicks[key] = group_clicks.get(key, 0) + 1

    if platform:
        conv_q["platform"] = platform
    if status:
        conv_q["status"] = status
    if event:
        conv_q["event"] = {"$regex": f"^{event}$", "$options": "i"}

    conversions = await db["conversions"].find(conv_q).limit(MAX_REPORT_SCAN).to_list(length=MAX_REPORT_SCAN)

    totals = {"clicks": click_totals, "conversions": 0, "revenue": 0.0, "payout": 0.0, "margin": 0.0, "conversion_rate": 0.0}
    groups: dict[str, dict] = {}
    for conv in conversions:
        payout = _to_float(conv.get("payout"))
        revenue = _to_float(conv.get("advertiser_revenue"))
        key = str(conv.get(gk) or "—")
        row = groups.setdefault(key, {"key": key, "clicks": 0, "conversions": 0, "revenue": 0.0, "payout": 0.0})
        row["conversions"] += 1
        row["payout"] += payout
        row["revenue"] += revenue
        totals["conversions"] += 1
        totals["payout"] += payout
        totals["revenue"] += revenue

    rows = []
    for key, row in groups.items():
        clicks = group_clicks.get(key, 0) if gk != "event" else 0
        row["clicks"] = clicks
        row["margin"] = round(row["revenue"] - row["payout"], 2)
        row["conversion_rate"] = round(row["conversions"] / clicks * 100, 2) if clicks else None
        row["revenue"] = round(row["revenue"], 2)
        row["payout"] = round(row["payout"], 2)
        rows.append(row)
    rows.sort(key=lambda r: r["conversions"], reverse=True)

    totals["margin"] = round(totals["revenue"] - totals["payout"], 2)
    totals["revenue"] = round(totals["revenue"], 2)
    totals["payout"] = round(totals["payout"], 2)
    totals["conversion_rate"] = round(totals["conversions"] / click_totals * 100, 2) if click_totals else None
    return {"totals": totals, "rows": rows, "group_by": group_by}


def report_to_csv(report: dict) -> str:
    header = "group,clicks,conversions,revenue,payout,margin,conversion_rate_pct"
    lines = [header]
    for r in report["rows"]:
        lines.append(
            f"{r['key']},{r['clicks']},{r['conversions']},{r['revenue']},{r['payout']},{r['margin']},{r['conversion_rate'] if r['conversion_rate'] is not None else ''}"
        )
    t = report["totals"]
    lines.append(f"TOTAL,{t['clicks']},{t['conversions']},{t['revenue']},{t['payout']},{t['margin']},{t['conversion_rate'] if t['conversion_rate'] is not None else ''}")
    return "\n".join(lines) + "\n"
