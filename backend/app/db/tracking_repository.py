"""
tracking_links + clicks collections (Part 5).

tracking_links: {link_id, public_code, campaign_id, campaign_code,
publisher_id, publisher_code, manager_id, config_version, status,
created_at, created_by} — public_code is the short URL-safe public
identifier (spec §21/§27): never a Mongo _id, never a financial value.

clicks: one immutable document per accepted click, keyed by the
DigiSNR-generated digisnr_click_id (DGSNR...) — the authoritative
attribution identity (spec §5/§8). Original tracking parameters are
preserved at creation and never mutated (spec §9).
"""
import logging
import secrets
import string
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.exceptions import ConflictError, ServiceUnavailableError
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

LINKS_COLLECTION = "tracking_links"
CLICKS_COLLECTION = "clicks"

# URL-safe, unambiguous alphabet (no 0/O/1/I) — public codes must survive
# being read aloud and typed manually (spec §20: short, URL-safe, stable).
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CLICK_ID_ALPHABET = string.ascii_uppercase + string.digits

_MAX_ID_ATTEMPTS = 8


def generate_campaign_code() -> str:
    return "C" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(5))


def generate_link_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))


def generate_publisher_code() -> str:
    return "PUB" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(5))


def generate_click_id() -> str:
    return "DGSNR" + "".join(secrets.choice(_CLICK_ID_ALPHABET) for _ in range(10))


async def ensure_campaign_code(campaign_id: str) -> str:
    """Assigns the campaign's short public code exactly once (atomic $set-on-
    absent), then keeps it stable forever — codes must never change or
    existing public links would break (spec §20)."""
    db = get_database()
    try:
        for _ in range(_MAX_ID_ATTEMPTS):
            code = generate_campaign_code()
            updated = await db["campaigns"].find_one_and_update(
                {"campaign_id": campaign_id, "public_code": {"$exists": False}},
                {"$set": {"public_code": code}},
                return_document=True,
            )
            if updated is not None:
                return updated["public_code"]
            existing = await db["campaigns"].find_one({"campaign_id": campaign_id}, {"public_code": 1})
            if existing is None:
                raise ServiceUnavailableError("Campaign disappeared while assigning public code")
            if existing.get("public_code"):
                return existing["public_code"]
        raise ConflictError("Could not allocate a campaign code, please retry")
    except DuplicateKeyError:
        raise ConflictError("Campaign code collision, please retry")
    except PyMongoError as exc:
        raise ServiceUnavailableError("Campaign store unavailable") from exc


async def ensure_publisher_code(publisher_id: str) -> str:
    """Same assign-once semantics for the publisher's public routing code
    (spec §6: public identifier ↔ internal publisher_id mapping lives here)."""
    db = get_database()
    try:
        for _ in range(_MAX_ID_ATTEMPTS):
            code = generate_publisher_code()
            updated = await db["publishers"].find_one_and_update(
                {"publisher_id": publisher_id, "public_code": {"$exists": False}},
                {"$set": {"public_code": code}},
                return_document=True,
            )
            if updated is not None:
                return updated["public_code"]
            existing = await db["publishers"].find_one({"publisher_id": publisher_id}, {"public_code": 1})
            if existing is None:
                raise ServiceUnavailableError("Publisher disappeared while assigning public code")
            if existing.get("public_code"):
                return existing["public_code"]
        raise ConflictError("Could not allocate a publisher code, please retry")
    except PyMongoError as exc:
        raise ServiceUnavailableError("Publisher store unavailable") from exc


async def create_tracking_link(doc: dict) -> dict:
    db = get_database()
    for _ in range(_MAX_ID_ATTEMPTS):
        doc["public_code"] = generate_link_code()
        doc["link_id"] = "LNK" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        try:
            await db[LINKS_COLLECTION].insert_one(dict(doc))
            return doc
        except DuplicateKeyError:
            continue
        except PyMongoError as exc:
            raise ServiceUnavailableError("Tracking link store unavailable") from exc
    raise ConflictError("Could not allocate a tracking link code, please retry")


async def find_active_link(campaign_id: str, publisher_id: str) -> dict | None:
    db = get_database()
    try:
        return await db[LINKS_COLLECTION].find_one(
            {"campaign_id": campaign_id, "publisher_id": publisher_id, "status": "active"}
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Tracking link store unavailable") from exc


async def get_link_by_codes(campaign_code: str, link_code: str) -> dict | None:
    """Public-code → internal mapping (spec §2/§21). Both codes must match so
    a link code alone can never be transplanted onto another campaign."""
    db = get_database()
    try:
        return await db[LINKS_COLLECTION].find_one(
            {"campaign_code": campaign_code, "public_code": link_code}
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Tracking link store unavailable") from exc


async def list_links(*, campaign_id: str | None = None, publisher_id: str | None = None,
                     manager_id: str | None = None, limit: int = 200) -> list[dict]:
    db = get_database()
    query: dict = {}
    if campaign_id:
        query["campaign_id"] = campaign_id
    if publisher_id:
        query["publisher_id"] = publisher_id
    if manager_id:
        query["manager_id"] = manager_id
    try:
        cursor = db[LINKS_COLLECTION].find(query).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Tracking link store unavailable") from exc


async def insert_click(doc: dict) -> dict:
    db = get_database()
    for _ in range(_MAX_ID_ATTEMPTS):
        doc["digisnr_click_id"] = generate_click_id()
        try:
            await db[CLICKS_COLLECTION].insert_one(dict(doc))
            return doc
        except DuplicateKeyError:
            continue
        except PyMongoError as exc:
            raise ServiceUnavailableError("Click store unavailable") from exc
    raise ConflictError("Could not allocate a click id, please retry")


async def count_clicks(campaign_id: str, since: datetime | None = None) -> int:
    db = get_database()
    query: dict = {"campaign_id": campaign_id}
    if since is not None:
        query["click_created_at"] = {"$gte": since}
    try:
        return await db[CLICKS_COLLECTION].count_documents(query)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Click store unavailable") from exc


async def count_clicks_for_link(link_id: str) -> int:
    db = get_database()
    try:
        return await db[CLICKS_COLLECTION].count_documents({"link_id": link_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Click store unavailable") from exc


async def count_clicks_for_publisher(publisher_id: str) -> int:
    db = get_database()
    try:
        return await db[CLICKS_COLLECTION].count_documents({"publisher_id": publisher_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Click store unavailable") from exc


async def list_clicks_for_publisher(publisher_id: str, skip: int = 0, limit: int = 50) -> list[dict]:
    db = get_database()
    try:
        cursor = db[CLICKS_COLLECTION].find({"publisher_id": publisher_id}).sort("click_created_at", -1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Click store unavailable") from exc


async def update_click_params(digisnr_click_id: str, params: dict) -> None:
    """Rewrite the stored parameter snapshot (used once, right after the
    click id exists, to expand a literal {click_id} inside p1..p10)."""
    sets: dict = {"original_params": params}
    for i in range(1, 11):
        if f"p{i}" in params:
            sets[f"sub_id_{i}"] = params[f"p{i}"]
    try:
        await get_database()[CLICKS_COLLECTION].update_one({"digisnr_click_id": digisnr_click_id}, {"$set": sets})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Click store unavailable") from exc


async def list_clicks_filtered(publisher_id: str, skip: int, limit: int, campaign_id: str | None = None,
                               date_from: datetime | None = None, date_to: datetime | None = None,
                               search: str | None = None) -> list[dict]:
    q: dict = {"publisher_id": publisher_id}
    if campaign_id:
        q["campaign_id"] = campaign_id
    if date_from or date_to:
        q["click_created_at"] = {k: v for k, v in (("$gte", date_from), ("$lte", date_to)) if v}
    if search:
        q["$or"] = [{"digisnr_click_id": {"$regex": "^" + __import__("re").escape(search)}},
                    {"ip": {"$regex": "^" + __import__("re").escape(search)}}]
    try:
        cur = get_database()[CLICKS_COLLECTION].find(q).sort("click_created_at", -1).skip(skip).limit(limit)
        return await cur.to_list(length=limit)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Click store unavailable") from exc


async def clicks_for_campaign(publisher_id: str, campaign_id: str, limit: int = 5000) -> list[dict]:
    try:
        cur = get_database()[CLICKS_COLLECTION].find(
            {"publisher_id": publisher_id, "campaign_id": campaign_id},
            {"_id": 0, "user_agent": 1, "country": 1, "city": 1}).limit(limit)
        return await cur.to_list(length=limit)
    except PyMongoError as exc:
        raise ServiceUnavailableError("Click store unavailable") from exc
