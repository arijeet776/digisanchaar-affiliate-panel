"""Click report — one row per click, scoped by role.

Everyone sees: campaign title, DigiSNR click id, publisher id, campaign id, the
click time (UTC here; the UI renders it in IST) and the click IP. Only the
Super Admin also gets the advertiser's own click id. Managers are pinned to their own
publishers and publishers to their own clicks, server-side.
"""
from datetime import datetime, timedelta, timezone

from app.core.enums import Role
from app.core.exceptions import ForbiddenError, ServiceUnavailableError
from app.core.rbac import CurrentUser
from app.db import campaign_repository, manager_repository, publisher_repository
from app.db.mongodb import get_database

MAX_PAGE_SIZE = 200


def _day(value: str | None, end: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return d + timedelta(days=1) if end else d


async def list_clicks(user: CurrentUser, *, campaign_id: str | None, publisher_id: str | None,
                      date_from: str | None, date_to: str | None, search: str | None,
                      page: int, page_size: int) -> dict:
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    query: dict = {}
    if user.role == Role.MANAGER:
        profile = await manager_repository.get_manager_by_user_id(user.user_id)
        if profile is None:
            raise ForbiddenError("Manager profile not found")
        query["manager_id"] = profile["manager_id"]
    elif user.role == Role.PUBLISHER:
        profile = await publisher_repository.get_publisher_by_user_id(user.user_id)
        if profile is None:
            raise ForbiddenError("Publisher profile not found")
        query["publisher_id"] = profile["publisher_id"]
        publisher_id = None  # a publisher can never widen the scope
    if campaign_id:
        query["campaign_id"] = campaign_id
    if publisher_id:
        query["publisher_id"] = publisher_id
    start, end = _day(date_from), _day(date_to, end=True)
    if start or end:
        window: dict = {}
        if start:
            window["$gte"] = start
        if end:
            window["$lt"] = end
        query["click_created_at"] = window
    if search:
        query["digisnr_click_id"] = search.strip()

    is_admin = user.role == Role.SUPER_ADMIN
    col = get_database()["clicks"]
    try:
        total = await col.count_documents(query)
        docs = await (col.find(query).sort("click_created_at", -1)
                      .skip((page - 1) * page_size).limit(page_size).to_list(length=page_size))
    except Exception as exc:  # noqa: BLE001
        raise ServiceUnavailableError("Click store unavailable") from exc

    titles: dict[str, str | None] = {}
    items = []
    for d in docs:
        cid = d["campaign_id"]
        if cid not in titles:
            camp = await campaign_repository.get_campaign(cid)
            titles[cid] = camp["summary"]["name"] if camp else None
        row = {
            "campaign_title": titles[cid],
            "click_id": d["digisnr_click_id"],
            "publisher_id": d["publisher_id"],
            "campaign_id": cid,
            "clicked_at": d.get("click_created_at"),
            # IP is shown to every role (publisher / manager / super admin), scoped to their own clicks above.
            "ip": d.get("ip"),
        }
        if is_admin:
            row["advertiser_click_id"] = d.get("external_click_id")
        items.append(row)
    return {"items": items, "total": total, "page": page, "page_size": page_size, "show_admin_columns": is_admin}
