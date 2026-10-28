"""
Manager panel services (Part 4, spec §49). Every function is scoped to the
CALLER's own manager_id, resolved fresh from the database — never from a
client-supplied value. A manager can never read or act on another manager's
publishers, and never reaches Owner/Super-Admin-only controls.
"""
import logging

from bson import ObjectId

from app.core.enums import AccountStatus, CampaignStatus
from app.core.exceptions import ForbiddenError, NotFoundError
from app.db import campaign_repository, manager_repository, publisher_repository
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

_TRACKING_UNAVAILABLE = {
    "available": False,
    "value": None,
    "reason": "Live tracking metrics become available once the tracking engine is enabled.",
}


async def get_manager_profile(actor_user_id: str) -> dict:
    profile = await manager_repository.get_manager_by_user_id(actor_user_id)
    if profile is None:
        raise ForbiddenError("Manager profile not found for current user")
    return profile


async def get_me(actor_user_id: str) -> dict:
    profile = await get_manager_profile(actor_user_id)
    db = get_database()
    user_doc = await db["users"].find_one({"_id": ObjectId(actor_user_id)})
    return {
        "user_id": actor_user_id,
        "manager_id": profile["manager_id"],
        "display_name": profile["display_name"],
        "mobile": profile.get("mobile"),
        "email": user_doc["email"] if user_doc else None,
    }


async def get_dashboard(actor_user_id: str) -> dict:
    profile = await get_manager_profile(actor_user_id)
    manager_id = profile["manager_id"]

    publishers = await publisher_repository.list_publishers_by_manager(manager_id)
    db = get_database()
    counts = {"total": 0, "active": 0, "pending": 0, "rejected": 0}
    for pub in publishers:
        user_doc = await db["users"].find_one({"_id": ObjectId(pub["user_id"])})
        if user_doc is None:
            continue
        counts["total"] += 1
        status = user_doc["account_status"]
        if status == AccountStatus.ACTIVE.value:
            counts["active"] += 1
        elif status == AccountStatus.PENDING.value:
            counts["pending"] += 1
        elif status == AccountStatus.REJECTED.value:
            counts["rejected"] += 1

    _docs, active_campaign_count = await campaign_repository.list_campaigns(
        status=CampaignStatus.ACTIVE, platform=None, search=None, skip=0, limit=1
    )

    return {
        "manager_id": manager_id,
        "display_name": profile["display_name"],
        "publishers": counts,
        "available_campaigns": active_campaign_count,
        "clicks": dict(_TRACKING_UNAVAILABLE),
        "conversions": dict(_TRACKING_UNAVAILABLE),
        "earnings": dict(_TRACKING_UNAVAILABLE),
    }


def _to_manager_campaign(doc: dict, config: dict) -> dict:
    """Manager-facing projection: advertiser rates ARE permitted (spec §6);
    the advertiser tracking URL and internal notes are NOT included."""
    summary = doc["summary"]
    return {
        "campaign_id": doc["campaign_id"],
        "name": summary["name"],
        "status": doc["status"],
        "advertiser_name": summary.get("advertiser_name"),
        "platform": summary.get("platform"),
        "payout_min": config.get("payout_min"),
        "payout_max": config.get("payout_max"),
        "events": [
            {
                "event_name": e["event_name"],
                "payout": e["payout"],
                "completion_source": e["completion_source"],
            }
            for e in config.get("events", [])
        ],
        "daily_cap": config.get("daily_cap"),
        "overall_cap": config.get("overall_cap"),
    }


async def list_available_campaigns() -> list[dict]:
    """Managers see ACTIVE network campaigns their publishers can run. Draft,
    paused, ended and purged campaigns are not exposed to the manager panel."""
    docs, _total = await campaign_repository.list_campaigns(
        status=CampaignStatus.ACTIVE, platform=None, search=None, skip=0, limit=500
    )
    result = []
    for doc in docs:
        config = await campaign_repository.get_current_config(doc)
        if config is not None:
            result.append(_to_manager_campaign(doc, config))
    return result


async def get_available_campaign(campaign_id: str) -> dict:
    doc = await campaign_repository.get_campaign(campaign_id)
    if doc is None or doc["status"] != CampaignStatus.ACTIVE.value:
        # 404 (not 403) — a manager must not be able to enumerate the
        # existence of draft/ended campaigns.
        raise NotFoundError("Campaign not found")
    config = await campaign_repository.get_current_config(doc)
    if config is None:
        raise NotFoundError("Campaign not found")
    detail = _to_manager_campaign(doc, config)
    detail.update(
        {
            "description": config.get("description"),
            "instructions": config.get("instructions"),
            "postback_platform": config.get("postback_platform"),
            "created_at": doc["created_at"],
        }
    )
    return detail
