"""
Conversion + postback storage (Part 6).

conversions: one document per accepted conversion. Idempotency is a real
database guarantee — a UNIQUE index on idempotency_key (platform + external
conversion id + event + DigiSanchaar click), so a duplicate postback can never
create a second conversion even under concurrent delivery (spec §23).

inbound_postbacks: every received postback, processed or not (spec §18).
outbound_postbacks: every publisher delivery with attempts (spec §19).
postback_endpoints: secure, revocable, per-campaign inbound URLs (spec §21).
publisher_postback_configs: versioned publisher postback templates (spec §20).
"""
import asyncio
import logging
import secrets
import string
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.exceptions import ConflictError, ServiceUnavailableError
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

_ALPHABET = string.ascii_uppercase + string.digits


def _new_id(prefix: str, n: int = 12) -> str:
    return f"{prefix}_" + "".join(secrets.choice(_ALPHABET) for _ in range(n))


def generate_conversion_id() -> str:
    return _new_id("QXCNV")


def generate_postback_id() -> str:
    return _new_id("QXPB")


def generate_outbound_id() -> str:
    return _new_id("QXOB")


def generate_endpoint_token() -> str:
    return secrets.token_urlsafe(24)


async def create_endpoint(campaign_id: str, platform: str, created_by: str) -> dict:
    db = get_database()
    now = datetime.now(timezone.utc)
    doc = {
        "endpoint_id": _new_id("QPEP", 8),
        "token": generate_endpoint_token(),
        "campaign_id": campaign_id,
        "platform": platform,
        "status": "active",
        "received_count": 0,
        "failure_count": 0,
        "last_received_at": None,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db["postback_endpoints"].insert_one(doc)
        return doc
    except PyMongoError as exc:
        raise ServiceUnavailableError("Postback store unavailable") from exc


async def get_endpoint_by_token(platform: str, token: str) -> dict | None:
    db = get_database()
    try:
        return await db["postback_endpoints"].find_one({"platform": platform, "token": token})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Postback store unavailable") from exc


async def get_endpoint(endpoint_id: str) -> dict | None:
    db = get_database()
    try:
        return await db["postback_endpoints"].find_one({"endpoint_id": endpoint_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Postback store unavailable") from exc


async def list_endpoints(campaign_id: str | None = None) -> list[dict]:
    db = get_database()
    query = {"campaign_id": campaign_id} if campaign_id else {}
    try:
        return await db["postback_endpoints"].find(query).sort("created_at", -1).to_list(length=500)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Postback store unavailable") from exc


async def set_endpoint_status(endpoint_id: str, status: str) -> dict | None:
    db = get_database()
    try:
        await db["postback_endpoints"].update_one(
            {"endpoint_id": endpoint_id},
            {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}},
        )
        return await get_endpoint(endpoint_id)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Postback store unavailable") from exc


async def bump_endpoint_stats(endpoint_id: str, failed: bool) -> None:
    db = get_database()
    try:
        await db["postback_endpoints"].update_one(
            {"endpoint_id": endpoint_id},
            {
                "$set": {"last_received_at": datetime.now(timezone.utc)},
                "$inc": {"received_count": 1, **({"failure_count": 1} if failed else {})},
            },
        )
    except PyMongoError as exc:
        logger.error("endpoint stat bump failed: %s", exc)


async def insert_conversion(doc: dict) -> tuple[dict, bool]:
    """Returns (doc, created). created=False means the idempotency unique index
    rejected a duplicate — the existing conversion is returned instead (§23)."""
    db = get_database()
    doc.setdefault("conversion_id", generate_conversion_id())
    doc.setdefault("conversion_created_at", datetime.now(timezone.utc))
    try:
        await db["conversions"].insert_one(dict(doc))
        return doc, True
    except DuplicateKeyError:
        existing = await db["conversions"].find_one({"idempotency_key": doc["idempotency_key"]})
        if existing is None:
            raise ConflictError("Duplicate conversion id, please retry")
        return existing, False
    except PyMongoError as exc:
        raise ServiceUnavailableError("Conversion store unavailable") from exc


async def update_conversion_status(conversion_id: str, status: str | None, raw_status: str | None) -> dict | None:
    """Legitimate status updates to an EXISTING conversion (spec §20) — the
    rest of the document is immutable."""
    db = get_database()
    try:
        await db["conversions"].update_one(
            {"conversion_id": conversion_id},
            {"$set": {"status": status, "raw_status": raw_status, "updated_at": datetime.now(timezone.utc)}},
        )
        return await db["conversions"].find_one({"conversion_id": conversion_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Conversion store unavailable") from exc


async def get_click(digisnr_click_id: str) -> dict | None:
    db = get_database()
    try:
        return await db["clicks"].find_one({"digisnr_click_id": digisnr_click_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Click store unavailable") from exc


async def log_inbound(doc: dict) -> dict:
    db = get_database()
    doc.setdefault("postback_id", generate_postback_id())
    doc.setdefault("received_at", datetime.now(timezone.utc))
    try:
        await db["inbound_postbacks"].insert_one(dict(doc))
        return doc
    except PyMongoError as exc:
        raise ServiceUnavailableError("Postback log store unavailable") from exc


async def list_inbound(platform=None, campaign_id=None, processing_status=None, skip=0, limit=50) -> tuple[list[dict], int]:
    db = get_database()
    query: dict = {}
    if platform:
        query["platform"] = platform
    if campaign_id:
        query["campaign_id"] = campaign_id
    if processing_status:
        query["processing_status"] = processing_status
    try:
        total = await db["inbound_postbacks"].count_documents(query)
        items = await db["inbound_postbacks"].find(query).sort("received_at", -1).skip(skip).limit(limit).to_list(length=limit)
        return items, total
    except PyMongoError as exc:
        raise ServiceUnavailableError("Postback log store unavailable") from exc


async def _latest_config(publisher_id: str, campaign_id: str | None) -> dict | None:
    return await get_database()["publisher_postback_configs"].find_one(
        {"publisher_id": publisher_id, "campaign_id": campaign_id}, sort=[("version", -1)]
    )


async def get_postback_config(publisher_id: str, campaign_id: str | None) -> dict | None:
    """Deterministic precedence (exactly ONE config is ever used per conversion):
    1) the publisher's campaign-specific config, if its LATEST version is enabled;
    2) otherwise the publisher's Global Postback (campaign_id=None), if its
       LATEST version is enabled and not deleted;
    3) otherwise none. A disabled/deleted latest version is never resurrected
       from an older enabled version."""
    try:
        if campaign_id is not None:
            doc = await _latest_config(publisher_id, campaign_id)
            if doc and doc.get("enabled") and not doc.get("deleted"):
                return doc
        doc = await _latest_config(publisher_id, None)
        if doc and doc.get("enabled") and not doc.get("deleted"):
            return doc
        return None
    except PyMongoError as exc:
        raise ServiceUnavailableError("Postback config store unavailable") from exc


async def get_latest_global_config(publisher_id: str) -> dict | None:
    """Latest Global Postback version regardless of enabled flag (for display)."""
    try:
        return await _latest_config(publisher_id, None)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Postback config store unavailable") from exc


async def next_config_version(publisher_id: str, campaign_id: str | None) -> int:
    db = get_database()
    try:
        doc = await db["publisher_postback_configs"].find_one(
            {"publisher_id": publisher_id, "campaign_id": campaign_id}, sort=[("version", -1)]
        )
        return (doc["version"] + 1) if doc else 1
    except PyMongoError as exc:
        raise ServiceUnavailableError("Postback config store unavailable") from exc


async def insert_config_version(doc: dict) -> dict:
    db = get_database()
    doc.setdefault("created_at", datetime.now(timezone.utc))
    try:
        await db["publisher_postback_configs"].insert_one(dict(doc))
        return doc
    except PyMongoError as exc:
        raise ServiceUnavailableError("Postback config store unavailable") from exc


async def log_outbound(doc: dict) -> dict:
    db = get_database()
    doc.setdefault("outbound_id", generate_outbound_id())
    doc.setdefault("created_at", datetime.now(timezone.utc))
    try:
        await db["outbound_postbacks"].insert_one(dict(doc))
        return doc
    except PyMongoError as exc:
        raise ServiceUnavailableError("Outbound log store unavailable") from exc


async def get_outbound(outbound_id: str) -> dict | None:
    db = get_database()
    try:
        return await db["outbound_postbacks"].find_one({"outbound_id": outbound_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Outbound log store unavailable") from exc


async def list_outbound(publisher_id=None, campaign_id=None, skip=0, limit=50) -> tuple[list[dict], int]:
    db = get_database()
    query: dict = {}
    if publisher_id:
        query["publisher_id"] = publisher_id
    if campaign_id:
        query["campaign_id"] = campaign_id
    try:
        total = await db["outbound_postbacks"].count_documents(query)
        items = await db["outbound_postbacks"].find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
        return items, total
    except PyMongoError as exc:
        raise ServiceUnavailableError("Outbound log store unavailable") from exc


async def list_conversions_for_publisher(publisher_id: str, skip: int = 0, limit: int = 50) -> list[dict]:
    db = get_database()
    try:
        cursor = db["conversions"].find({"publisher_id": publisher_id}).sort("conversion_created_at", -1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Conversion store unavailable") from exc


async def count_conversions_for_publisher(publisher_id: str) -> int:
    db = get_database()
    try:
        return await db["conversions"].count_documents({"publisher_id": publisher_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Conversion store unavailable") from exc


async def sum_earnings_for_publisher(publisher_id: str) -> float:
    """Sum of this publisher's own payouts — the publisher-facing earnings
    figure. Authoritative ledger posting arrives with the financial part."""
    db = get_database()
    try:
        pipeline = [
            {"$match": {"publisher_id": publisher_id, "payout": {"$ne": None},
                         "approval_status": {"$nin": ["pending_report", "rejected"]}}},
            {"$group": {"_id": None, "total": {"$sum": "$payout"}}},
        ]
        result = await db["conversions"].aggregate(pipeline).to_list(length=1)
        return result[0]["total"] if result else 0
    except PyMongoError as exc:
        raise ServiceUnavailableError("Conversion store unavailable") from exc


async def transition_approval(conversion_id: str, from_states: list[str], to_state: str,
                              actor_user_id: str, note: str | None) -> dict | None:
    """Atomic conditional transition of the company-report approval state.
    Returns the updated doc, or None if the conversion wasn't in an allowed
    source state (already decided / concurrent decision / unknown id)."""
    try:
        return await get_database()["conversions"].find_one_and_update(
            {"conversion_id": conversion_id, "approval_status": {"$in": from_states}},
            {"$set": {"approval_status": to_state, "approval_decided_by": actor_user_id,
                      "approval_decided_at": datetime.now(timezone.utc), "approval_note": note,
                      "updated_at": datetime.now(timezone.utc)}},
            return_document=True, projection={"_id": 0},
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Conversion store unavailable") from exc


async def get_conversion(conversion_id: str) -> dict | None:
    try:
        return await get_database()["conversions"].find_one({"conversion_id": conversion_id}, {"_id": 0})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Conversion store unavailable") from exc


async def list_for_review(manager_id: str | None, approval_status: str | None, campaign_id: str | None,
                          skip: int, limit: int) -> tuple[list[dict], int]:
    q: dict = {}
    if manager_id:
        q["manager_id"] = manager_id
    if approval_status:
        q["approval_status"] = approval_status
    if campaign_id:
        q["campaign_id"] = campaign_id
    col = get_database()["conversions"]
    proj = {"_id": 0, "conversion_id": 1, "campaign_id": 1, "publisher_id": 1, "event": 1, "goal": 1, "status": 1,
            "payout": 1, "approval_status": 1, "approval_note": 1, "approval_decided_at": 1,
            "digisnr_click_id": 1, "postback_received_at": 1, "conversion_created_at": 1, "currency": 1}
    try:
        total = await col.count_documents(q)
        items = await col.find(q, proj).sort("conversion_created_at", -1).skip(skip).limit(limit).to_list(length=limit)
        return items, total
    except PyMongoError as exc:
        raise ServiceUnavailableError("Conversion store unavailable") from exc


IST = timezone(timedelta(hours=5, minutes=30))
_NOT_EARNING = ("pending_report", "rejected")


def _as_utc(v) -> datetime | None:
    """Stored timestamps may come back as datetime or ISO string (Supabase store)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def publisher_dashboard_stats(publisher_id: str) -> dict:
    """Own-data aggregates for the publisher dashboard.

    Everything time-based is the CURRENT CALENDAR MONTH in IST (the UI's
    timezone): month totals, the day-by-day trend and the earnings overview.
    Only CONFIRMED conversions count as earnings; pending_report/rejected never do.
    """
    db = get_database()
    now_ist = datetime.now(IST)
    month_start_ist = now_ist.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start = month_start_ist.astimezone(timezone.utc)
    days_in_month_so_far = now_ist.day
    try:
        async def month_totals(since: datetime | None) -> dict:
            q: dict = {"publisher_id": publisher_id}
            if since:
                q["conversion_created_at"] = {"$gte": since}
            rows = await db["conversions"].aggregate([
                {"$match": q},
                {"$group": {
                    "_id": None, "conversions": {"$sum": 1},
                    "earnings": {"$sum": {"$cond": [{"$and": [
                        {"$ne": ["$payout", None]},
                        {"$not": [{"$in": [{"$ifNull": ["$approval_status", "confirmed"]}, ["pending_report", "rejected"]]}]}]},
                        "$payout", 0]}},
                    "pending": {"$sum": {"$cond": [{"$eq": ["$approval_status", "pending_report"]}, {"$ifNull": ["$payout", 0]}, 0]}},
                }},
            ]).to_list(length=1)
            r = rows[0] if rows else {}
            return {"conversions": r.get("conversions", 0), "earnings": r.get("earnings", 0), "pending": r.get("pending", 0)}

        clicks_col = db["clicks"]
        top_pipeline = [
            {"$match": {"publisher_id": publisher_id}},
            {"$group": {"_id": "$campaign_id", "conversions": {"$sum": 1},
                        "earnings": {"$sum": {"$cond": [{"$and": [
                            {"$ne": ["$payout", None]},
                            {"$not": [{"$in": [{"$ifNull": ["$approval_status", "confirmed"]}, ["pending_report", "rejected"]]}]}]},
                            "$payout", 0]}}}},
        ]
        (month_clicks, month_rows, top, clicks_by_campaign, month_conv, lifetime_conv) = await asyncio.gather(
            clicks_col.count_documents({"publisher_id": publisher_id, "click_created_at": {"$gte": month_start}}),
            db["conversions"].find(
                {"publisher_id": publisher_id, "conversion_created_at": {"$gte": month_start}},
                {"conversion_created_at": 1, "payout": 1, "approval_status": 1},
            ).to_list(length=50000),
            db["conversions"].aggregate(top_pipeline).to_list(length=200),
            clicks_col.aggregate([
                {"$match": {"publisher_id": publisher_id}},
                {"$group": {"_id": "$campaign_id", "clicks": {"$sum": 1}}},
            ]).to_list(length=200),
            month_totals(month_start),
            month_totals(None),
        )

        # Day-by-day for the current month (IST), zero-filled up to today.
        daily = {d: {"conversions": 0, "earnings": 0.0} for d in range(1, days_in_month_so_far + 1)}
        for r in month_rows:
            ts = _as_utc(r.get("conversion_created_at"))
            if ts is None:
                continue
            day = ts.astimezone(IST).day
            if day not in daily:
                continue
            daily[day]["conversions"] += 1
            status = r.get("approval_status") or "confirmed"
            if r.get("payout") is not None and status not in _NOT_EARNING:
                daily[day]["earnings"] += float(r["payout"])
        daily_series = []
        for d in range(1, days_in_month_so_far + 1):
            day_date = month_start_ist.replace(day=d)
            daily_series.append({
                "day": day_date.strftime("%Y-%m-%d"),
                "label": day_date.strftime("%d %b"),
                "conversions": daily[d]["conversions"],
                "earnings": round(daily[d]["earnings"], 2),
            })

        merged: dict = {c["_id"]: {"campaign_id": c["_id"], "clicks": c["clicks"], "conversions": 0, "earnings": 0} for c in clicks_by_campaign}
        for t in top:
            merged.setdefault(t["_id"], {"campaign_id": t["_id"], "clicks": 0, "conversions": 0, "earnings": 0}).update(
                conversions=t["conversions"], earnings=t["earnings"])
        top_campaigns = sorted(merged.values(), key=lambda r: (r["clicks"], r["conversions"]), reverse=True)[:5]
        return {
            "month": {"clicks": month_clicks, **month_conv},
            "lifetime": lifetime_conv,
            "daily": daily_series,
            "top_campaigns": top_campaigns,
            "month_label": now_ist.strftime("%B %Y"),
        }
    except PyMongoError as exc:
        raise ServiceUnavailableError("Conversion store unavailable") from exc


async def list_conversions_filtered(publisher_id: str, skip: int, limit: int, campaign_id: str | None = None,
                                    date_from: datetime | None = None, date_to: datetime | None = None,
                                    approval_status: str | None = None, search: str | None = None) -> list[dict]:
    q: dict = {"publisher_id": publisher_id}
    if campaign_id:
        q["campaign_id"] = campaign_id
    if approval_status:
        q["approval_status"] = approval_status
    if date_from or date_to:
        q["conversion_created_at"] = {k: v for k, v in (("$gte", date_from), ("$lte", date_to)) if v}
    if search:
        q["digisnr_click_id"] = {"$regex": "^" + __import__("re").escape(search)}
    try:
        cur = get_database()["conversions"].find(q).sort("conversion_created_at", -1).skip(skip).limit(limit)
        return await cur.to_list(length=limit)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Conversion store unavailable") from exc
