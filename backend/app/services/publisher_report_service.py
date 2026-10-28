"""
Publisher-facing report rows + background Export Center (Part 17).

Everything here reads REAL click/conversion records. The publisher projection
is the security boundary: advertiser revenue, upstream payout and margin are
never selected, and every query is pinned to the caller's publisher_id by the
endpoint (never taken from the request).

Payout: `conversion.payout` is the publisher payout resolved server-side from
the campaign's configured event payout at conversion time (what THIS publisher
earns for THAT event). It is expressed in the platform currency; the
advertiser's own currency (a postback field) is internal and never shown as
the publisher's payout currency.
"""
import asyncio
import csv
import io
import json
import logging
import re
import secrets
import string
from datetime import datetime, timezone

from pymongo.errors import PyMongoError

from app.core import audit_actions
from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError, ValidationAppError
from app.db.audit_repository import record as audit_record
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

PLATFORM_CURRENCY = "INR"
P_KEYS = [f"p{i}" for i in range(1, 11)]
EXPORT_JOBS = "export_jobs"
MAX_EXPORT_ROWS = 20000          # one CSV/JSON document stays well under Mongo's 16MB cap
MAX_ACTIVE_JOBS_PER_PUBLISHER = 3
_ID_ALPHABET = string.ascii_uppercase + string.digits


# ----------------------------------------------------------------- rows ----

def _p_values(click: dict | None) -> dict:
    original = (click or {}).get("original_params") or {}
    return {k: original.get(k) for k in P_KEYS}


def click_row(click: dict, campaign_names: dict[str, str]) -> dict:
    return {
        "digisnr_click_id": click["digisnr_click_id"],
        "campaign_id": click["campaign_id"],
        "campaign_name": campaign_names.get(click["campaign_id"]),
        "click_created_at": click["click_created_at"],
        "country": click.get("country"),
        "state": click.get("state"),
        "city": click.get("city"),
        "ip": click.get("ip"),
        **_p_values(click),
    }


def conversion_row(conv: dict, click: dict | None, campaign_names: dict[str, str]) -> dict:
    """Publisher-safe: no revenue / upstream payout / margin keys, ever."""
    return {
        "conversion_id": conv["conversion_id"],
        "campaign_id": conv["campaign_id"],
        "campaign_name": campaign_names.get(conv["campaign_id"]),
        "event": conv.get("event"),             # the ACTUAL event of this record
        "status": conv.get("status"),
        "approval_status": conv.get("approval_status") or "confirmed",
        "payout": conv.get("payout"),
        "currency": PLATFORM_CURRENCY if conv.get("payout") is not None else None,
        "digisnr_click_id": conv["digisnr_click_id"],
        "conversion_created_at": conv["conversion_created_at"],
        "postback_received_at": conv.get("postback_received_at"),
        "country": (click or {}).get("country"),
        "state": (click or {}).get("state"),
        "city": (click or {}).get("city"),
        "ip": (click or {}).get("ip"),
        **_p_values(click),
    }


GROUP_FETCH_CAP = 5000  # conversions read per grouped report request (groups are paged in memory)


def _as_utc(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def grouped_conversion_rows(convs: list[dict], clicks: dict[str, dict], campaign_names: dict[str, str]) -> list[dict]:
    """ONE row per DigiSNR click ID (Conversion Report only).

    The row date is the ORIGINAL click date and never changes when a later event
    arrives. Every conversion record for that click (Install, Register, KYC, ...)
    becomes an event badge on the same row with its own payout. Publisher-safe:
    same projection as conversion_row (no revenue / upstream payout / margin)."""
    groups: dict[str, dict] = {}
    for c in convs:
        cid = c["digisnr_click_id"]
        click = clicks.get(cid)
        row = conversion_row(c, click, campaign_names)
        g = groups.get(cid)
        if g is None:
            g = {
                "digisnr_click_id": cid,
                "campaign_id": row["campaign_id"],
                "campaign_name": row["campaign_name"],
                "date": (click or {}).get("click_created_at") or row["conversion_created_at"],
                "country": row["country"], "state": row["state"], "city": row["city"], "ip": row["ip"],
                **_p_values(click),
                "events": [],
                "total_payout": 0.0,
                "currency": PLATFORM_CURRENCY,
            }
            groups[cid] = g
        g["events"].append({
            "conversion_id": row["conversion_id"],
            "event": row["event"],
            "status": row["status"],
            "approval_status": row["approval_status"],
            "payout": row["payout"],
            "currency": row["currency"],
            "conversion_created_at": row["conversion_created_at"],
            "postback_received_at": row["postback_received_at"],
        })
        if row["approval_status"] != "rejected" and row["payout"] is not None:
            g["total_payout"] += float(row["payout"])

    out = list(groups.values())
    for g in out:
        g["events"].sort(key=lambda e: _as_utc(e["conversion_created_at"]))  # oldest event first
        g["total_payout"] = round(g["total_payout"], 2)
    out.sort(key=lambda g: _as_utc(g["date"]), reverse=True)
    return out


async def campaign_name_map(publisher_id: str) -> dict[str, str]:
    from app.db import campaign_repository, tracking_repository

    links = await tracking_repository.list_links(publisher_id=publisher_id)
    cids = list(dict.fromkeys(link["campaign_id"] for link in links))
    # One campaign lookup per distinct campaign, all concurrently.
    campaigns = await asyncio.gather(*[campaign_repository.get_campaign(cid) for cid in cids])
    names: dict[str, str] = {}
    for cid, campaign in zip(cids, campaigns):
        if campaign:
            names[cid] = campaign["summary"]["name"]
    return names


async def clicks_by_ids(click_ids: list[str]) -> dict[str, dict]:
    if not click_ids:
        return {}
    try:
        docs = await get_database()["clicks"].find({"digisnr_click_id": {"$in": list(set(click_ids))}}).to_list(length=len(click_ids))
    except PyMongoError as exc:
        raise ServiceUnavailableError("Click store unavailable") from exc
    return {d["digisnr_click_id"]: d for d in docs}


def _conv_query(publisher_id: str, campaign_id, date_from, date_to) -> dict:
    q: dict = {"publisher_id": publisher_id}
    if campaign_id:
        q["campaign_id"] = campaign_id
    if date_from or date_to:
        q["conversion_created_at"] = {k: v for k, v in (("$gte", date_from), ("$lte", date_to)) if v}
    return q


async def event_summary(publisher_id: str, campaign_id=None, date_from=None, date_to=None) -> list[dict]:
    """Per-event totals from REAL conversion records (no zero/fake events).
    Rejected company-report outcomes are excluded from payout totals."""
    q = _conv_query(publisher_id, campaign_id, date_from, date_to)
    pipeline = [
        {"$match": q},
        {"$group": {
            "_id": "$event",
            "conversions": {"$sum": 1},
            "payout": {"$sum": {"$cond": [{"$eq": ["$approval_status", "rejected"]}, 0, {"$ifNull": ["$payout", 0]}]}},
        }},
        {"$sort": {"conversions": -1}},
    ]
    try:
        rows = await get_database()["conversions"].aggregate(pipeline).to_list(length=200)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Conversion store unavailable") from exc
    return [
        {"event": r["_id"], "conversions": r["conversions"], "payout": round(float(r["payout"] or 0), 2),
         "currency": PLATFORM_CURRENCY}
        for r in rows
    ]


# --------------------------------------------------------------- export ----

def _new_job_id() -> str:
    return "EXP" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(10))


def _csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection from publisher-controlled
    values (p1..p10 are free text from a tracking URL)."""
    if value is None:
        return ""
    text = value.isoformat() if isinstance(value, datetime) else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


CLICK_COLUMNS = ["Date", "Click ID", "Campaign", "Country", "State", "City", "IP"] + [k.upper() for k in P_KEYS]
CONVERSION_COLUMNS = ["Date", "Click ID", "Campaign", "Event", "Status", "Report Status", "Payout", "Currency",
                      "Country", "State", "City", "IP"] + [k.upper() for k in P_KEYS]


def _click_cells(r: dict) -> list:
    return [r["click_created_at"], r["digisnr_click_id"], r["campaign_name"] or r["campaign_id"],
            r["country"], r["state"], r["city"], r["ip"]] + [r[k] for k in P_KEYS]


def _conversion_cells(r: dict) -> list:
    return [r["conversion_created_at"], r["digisnr_click_id"], r["campaign_name"] or r["campaign_id"],
            r["event"], r["status"], r["approval_status"], r["payout"], r["currency"],
            r["country"], r["state"], r["city"], r["ip"]] + [r[k] for k in P_KEYS]


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationAppError("Invalid date")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def create_export_job(publisher_id: str, actor_user_id: str, kind: str, fmt: str,
                            campaign_id: str | None, date_from: str | None, date_to: str | None,
                            unique_ip: bool) -> dict:
    if kind not in ("clicks", "conversions"):
        raise ValidationAppError("kind must be clicks or conversions")
    if fmt not in ("csv", "json"):
        raise ValidationAppError("format must be csv or json")
    d_from, d_to = _parse_dt(date_from), _parse_dt(date_to)
    if d_from and d_to and (d_to - d_from).days > 90:
        raise ValidationAppError("Date range is limited to 90 days per export")
    if d_from and d_to and d_to < d_from:
        raise ValidationAppError("'To' must be after 'From'")
    db = get_database()
    try:
        active = await db[EXPORT_JOBS].count_documents(
            {"publisher_id": publisher_id, "status": {"$in": ["PENDING", "PROCESSING"]}})
        if active >= MAX_ACTIVE_JOBS_PER_PUBLISHER:
            raise ConflictError("You already have exports in progress. Please wait for them to finish.")
        doc = {
            "job_id": _new_job_id(), "publisher_id": publisher_id, "kind": kind, "format": fmt,
            "filters": {"campaign_id": campaign_id, "date_from": date_from, "date_to": date_to,
                        "unique_ip": bool(unique_ip) if kind == "clicks" else False},
            "status": "PENDING", "records": None, "truncated": False, "error": None,
            "created_at": datetime.now(timezone.utc), "completed_at": None,
        }
        await db[EXPORT_JOBS].insert_one(dict(doc))
    except PyMongoError as exc:
        raise ServiceUnavailableError("Export store unavailable") from exc
    await audit_record(audit_actions.EXPORT_JOB_REQUESTED, actor_user_id=actor_user_id,
                       metadata={"job_id": doc["job_id"], "kind": kind, "format": fmt})
    return doc


async def run_export_job(job_id: str) -> None:
    """Background worker. Atomic PENDING->PROCESSING claim means a job can only
    be built once even if triggered twice. Failures are recorded on the job."""
    db = get_database()
    job = await db[EXPORT_JOBS].find_one_and_update(
        {"job_id": job_id, "status": "PENDING"}, {"$set": {"status": "PROCESSING"}}, return_document=True)
    if job is None:
        return
    try:
        pid = job["publisher_id"]
        f = job["filters"]
        names = await campaign_name_map(pid)
        d_from, d_to = _parse_dt(f.get("date_from")), _parse_dt(f.get("date_to"))
        rows: list[dict] = []
        truncated = False
        seen_ips: set[str] = set()
        if job["kind"] == "clicks":
            q: dict = {"publisher_id": pid}
            if f.get("campaign_id"):
                q["campaign_id"] = f["campaign_id"]
            if d_from or d_to:
                q["click_created_at"] = {k: v for k, v in (("$gte", d_from), ("$lte", d_to)) if v}
            cursor = db["clicks"].find(q).sort("click_created_at", -1)
            async for c in cursor:
                if f.get("unique_ip"):
                    ip = c.get("ip") or ""
                    if ip in seen_ips:
                        continue
                    seen_ips.add(ip)
                if len(rows) >= MAX_EXPORT_ROWS:
                    truncated = True
                    break
                rows.append(click_row(c, names))
            cells, columns = _click_cells, CLICK_COLUMNS
        else:
            q = _conv_query(pid, f.get("campaign_id"), d_from, d_to)
            batch: list[dict] = []
            cursor = db["conversions"].find(q).sort("conversion_created_at", -1)
            async for cv in cursor:
                if len(batch) >= MAX_EXPORT_ROWS:
                    truncated = True
                    break
                batch.append(cv)
            clicks = await clicks_by_ids([c["digisnr_click_id"] for c in batch])
            rows = [conversion_row(c, clicks.get(c["digisnr_click_id"]), names) for c in batch]
            cells, columns = _conversion_cells, CONVERSION_COLUMNS

        if job["format"] == "json":
            content = json.dumps(rows, default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o))
        else:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(columns)
            for r in rows:
                w.writerow([_csv_safe(v) for v in cells(r)])
            content = buf.getvalue()
        await db[EXPORT_JOBS].update_one(
            {"job_id": job_id},
            {"$set": {"status": "COMPLETED", "records": len(rows), "truncated": truncated,
                      "content": content, "completed_at": datetime.now(timezone.utc)}})
    except Exception as exc:  # noqa: BLE001 - a failed job is recorded, never silent
        logger.error("export job %s failed: %s", job_id, exc)
        await db[EXPORT_JOBS].update_one(
            {"job_id": job_id},
            {"$set": {"status": "FAILED", "error": "Export failed. Please try again.",
                      "completed_at": datetime.now(timezone.utc)}})


def serialize_job(job: dict) -> dict:
    return {
        "job_id": job["job_id"], "kind": job["kind"], "format": job["format"], "status": job["status"],
        "records": job.get("records"), "truncated": bool(job.get("truncated")), "filters": job.get("filters") or {},
        "error": job.get("error"), "created_at": job["created_at"], "completed_at": job.get("completed_at"),
    }


async def list_jobs(publisher_id: str, kind: str | None, limit: int = 50) -> list[dict]:
    q: dict = {"publisher_id": publisher_id}
    if kind:
        q["kind"] = kind
    try:
        docs = await get_database()[EXPORT_JOBS].find(q, {"content": 0}).sort("created_at", -1).limit(limit).to_list(length=limit)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Export store unavailable") from exc
    return [serialize_job(d) for d in docs]


async def get_job_content(publisher_id: str, job_id: str) -> tuple[dict, str]:
    """Owner-scoped: another publisher's job id behaves as not-found."""
    if not re.fullmatch(r"EXP[A-Z0-9]{10}", job_id or ""):
        raise NotFoundError("Export not found")
    try:
        job = await get_database()[EXPORT_JOBS].find_one({"job_id": job_id, "publisher_id": publisher_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Export store unavailable") from exc
    if job is None:
        raise NotFoundError("Export not found")
    if job["status"] != "COMPLETED":
        raise ConflictError("This export is not ready yet")
    return job, job.get("content") or ""
