"""
system_settings collection — runtime-administered application configuration
(tracking domain first; later parts add more keys). One document per key:
{key, value, created_at, updated_at, updated_by}.

Spec §29: ENV provides bootstrap defaults; this collection holds the ACTIVE
runtime value, and the backend is the authoritative resolver — the frontend
never invents a production tracking domain.
"""
import logging
from datetime import datetime, timezone

from pymongo.errors import PyMongoError

from app.core.exceptions import ServiceUnavailableError
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

COLLECTION = "system_settings"
TRACKING_DOMAIN_KEY = "tracking_base_url"
ACCENT_THEME_KEY = "accent_theme"
WHATSAPP_GROUP_KEY = "whatsapp_group_link"


async def get_setting(key: str) -> dict | None:
    db = get_database()
    try:
        return await db[COLLECTION].find_one({"key": key})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Settings store unavailable") from exc


async def upsert_setting(key: str, value: str, updated_by: str) -> dict:
    db = get_database()
    now = datetime.now(timezone.utc)
    try:
        return await db[COLLECTION].find_one_and_update(
            {"key": key},
            {
                "$set": {"value": value, "updated_at": now, "updated_by": updated_by},
                "$setOnInsert": {"key": key, "created_at": now},
            },
            upsert=True,
            return_document=True,
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Settings store unavailable") from exc
