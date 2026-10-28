"""Super Admin broadcast messages shown on every Manager / Publisher Notifications page.

Stored as ONE JSON list in system_settings (key "announcements"), so no schema
change or SQL is needed. Removing a message deletes it from the list, which
makes it disappear for everyone immediately.
"""
import json
import secrets
from datetime import datetime, timezone

from app.core.enums import Role
from app.core.exceptions import NotFoundError
from app.db import settings_repository

KEY = "announcements"
MAX_ITEMS = 100
AUDIENCES = ("all", "managers", "publishers")


async def _load() -> list[dict]:
    row = await settings_repository.get_setting(KEY)
    if not row or not row.get("value"):
        return []
    try:
        data = json.loads(row["value"])
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


async def _save(items: list[dict], user_id: str) -> None:
    await settings_repository.upsert_setting(KEY, json.dumps(items), user_id)


def _visible(item: dict, role: Role) -> bool:
    if role == Role.SUPER_ADMIN:
        return True
    aud = item.get("audience", "all")
    return aud == "all" or (aud == "managers" and role == Role.MANAGER) or (aud == "publishers" and role == Role.PUBLISHER)


async def list_for(role: Role) -> list[dict]:
    items = [i for i in await _load() if _visible(i, role)]
    return sorted(items, key=lambda i: i.get("created_at", ""), reverse=True)


async def create(user_id: str, title: str, message: str, audience: str) -> dict:
    item = {
        "id": "ANN-" + secrets.token_hex(4).upper(),
        "title": title.strip(),
        "message": message.strip(),
        "audience": audience,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items = [item] + await _load()
    await _save(items[:MAX_ITEMS], user_id)
    return item


async def remove(user_id: str, announcement_id: str) -> None:
    items = await _load()
    kept = [i for i in items if i.get("id") != announcement_id]
    if len(kept) == len(items):
        raise NotFoundError("Message not found")
    await _save(kept, user_id)
