"""Campaign access (approval workflow).

Super Admin decides per campaign whether publishers may promote immediately
or must be approved first (campaign config `approval_mode`). Publishers
self-serve here; managers approve only their own publishers, Super Admin
approves any. Server-authoritative: publisher identity always comes from
the authenticated user, never the request body.
"""
from app.core import audit_actions
from app.core.enums import CampaignApplicationStatus, CampaignApprovalMode, CampaignStatus, Role
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.rbac import CurrentUser
from app.db import campaign_access_repository as repo
from app.db import campaign_repository, manager_repository, publisher_repository, tracking_repository
from app.db.audit_repository import record as audit_record
from app.services import tracking_service


async def _publisher_profile(user: CurrentUser) -> dict:
    p = await publisher_repository.get_publisher_by_user_id(user.user_id)
    if p is None:
        raise NotFoundError("Publisher profile not found for current user")
    return p


def _mode(config: dict | None) -> str:
    return (config or {}).get("approval_mode") or CampaignApprovalMode.PROMOTE_IMMEDIATELY.value


async def _link_for(campaign_id: str, publisher_id: str) -> dict | None:
    return await tracking_repository.find_active_link(campaign_id, publisher_id)


async def list_available(user: CurrentUser, skip: int, limit: int, search: str | None, category: str | None = None,
                         kind: str | None = None, country: str | None = None, mode: str | None = None,
                         sort: str = "newest") -> dict:
    """Active campaigns visible to a publisher, with their own access state.
    Projection is a whitelist — no advertiser URL, no postback config, no
    upstream revenue (Part 7 §52)."""
    profile = await _publisher_profile(user)
    campaigns, _ = await campaign_repository.list_campaigns(CampaignStatus.ACTIVE, None, search, 0, 500)
    access = {a["campaign_id"]: a for a in await repo.list_for_publisher(profile["publisher_id"])}
    items = []
    for c in campaigns:
        cfg = await campaign_repository.get_current_config(c) or {}
        if category and (cfg.get("category") or "") != category:
            continue
        if kind and (cfg.get("kind") or "standard") != kind:
            continue
        if country and country not in (cfg.get("countries") or []):
            continue
        if mode and _mode(cfg) != mode:
            continue
        acc = access.get(c["campaign_id"])
        link = await _link_for(c["campaign_id"], profile["publisher_id"])
        events = [{"event_name": e["event_name"], "payout": e["payout"]} for e in cfg.get("events", [])]
        items.append({
            "campaign_id": c["campaign_id"],
            "name": c["summary"]["name"],
            "logo_url": cfg.get("logo_url"),
            "description": cfg.get("description"),
            "platform": c["summary"].get("platform"),
            "status": c["status"],
            "approval_mode": _mode(cfg),
            "tracking_only": bool(cfg.get("tracking_only")),
            "category": cfg.get("category"),
            "kind": cfg.get("kind") or "standard",
            "countries": cfg.get("countries") or [],
            "created_at": c.get("created_at"),
            "tracking_window_hours": cfg.get("tracking_window_hours"),
            "events": events,
            "max_payout": max((e["payout"] for e in events), default=None),
            "access_status": acc["status"] if acc else None,
            "has_link": link is not None,
        })
    if sort == "payout":
        items.sort(key=lambda i: i["max_payout"] or 0, reverse=True)
    elif sort == "oldest":
        items.sort(key=lambda i: str(i["created_at"] or ""))
    else:
        items.sort(key=lambda i: str(i["created_at"] or ""), reverse=True)
    facets = {
        "categories": sorted({i["category"] for i in items if i["category"]}),
        "countries": sorted({c for i in items for c in i["countries"]}),
    }
    total = len(items)
    return {"items": items[skip:skip + limit], "total": total, "facets": facets}


async def request_access(user: CurrentUser, campaign_id: str) -> dict:
    profile = await _publisher_profile(user)
    campaign = await campaign_repository.get_campaign(campaign_id)
    if campaign is None or campaign["status"] != CampaignStatus.ACTIVE.value:
        raise NotFoundError("Campaign not available")
    cfg = await campaign_repository.get_current_config(campaign)
    publisher_id = profile["publisher_id"]

    existing = await repo.get(campaign_id, publisher_id)
    if existing and existing["status"] == CampaignApplicationStatus.REJECTED.value:
        raise ConflictError("Your access request for this campaign was rejected")

    if _mode(cfg) == CampaignApprovalMode.PROMOTE_IMMEDIATELY.value:
        doc, created = await repo.create(campaign_id, publisher_id, profile.get("manager_id"),
                                         CampaignApplicationStatus.APPROVED, decided_by="system")
        link = await tracking_service.generate_link_for_access(campaign_id, publisher_id, user.user_id)
        if created:
            await audit_record(audit_actions.CAMPAIGN_ACCESS_APPROVED, actor_user_id=user.user_id,
                               metadata={"campaign_id": campaign_id, "publisher_id": publisher_id, "auto": True})
        return {"access_status": doc["status"], "link": link}

    doc, created = await repo.create(campaign_id, publisher_id, profile.get("manager_id"),
                                     CampaignApplicationStatus.PENDING)
    if created:
        await audit_record(audit_actions.CAMPAIGN_ACCESS_REQUESTED, actor_user_id=user.user_id,
                           metadata={"campaign_id": campaign_id, "publisher_id": publisher_id})
    link = None
    if doc["status"] == CampaignApplicationStatus.APPROVED.value:
        link = await tracking_service.generate_link_for_access(campaign_id, publisher_id, user.user_id)
    return {"access_status": doc["status"], "link": link}


async def list_applications(user: CurrentUser, status: str | None, skip: int, limit: int) -> dict:
    manager_id = None
    if user.role == Role.MANAGER:
        m = await manager_repository.get_manager_by_user_id(user.user_id)
        if m is None:
            raise ForbiddenError("Manager profile not found")
        manager_id = m["manager_id"]
    items, total = await repo.list_filtered(manager_id, status, skip, limit)
    for it in items:
        c = await campaign_repository.get_campaign(it["campaign_id"])
        p = await publisher_repository.get_publisher_by_publisher_id(it["publisher_id"])
        it["campaign_name"] = c["summary"]["name"] if c else None
        it["publisher_name"] = p["display_name"] if p else None
    return {"items": items, "total": total}


async def decide(user: CurrentUser, access_id: str, approve: bool, note: str | None) -> dict:
    rec = await repo.get_by_id(access_id)
    if rec is None:
        raise NotFoundError("Access request not found")
    if user.role == Role.MANAGER:
        m = await manager_repository.get_manager_by_user_id(user.user_id)
        if m is None or rec.get("manager_id") != m["manager_id"]:
            raise NotFoundError("Access request not found")  # no existence leak across managers
    new = CampaignApplicationStatus.APPROVED if approve else CampaignApplicationStatus.REJECTED
    updated = await repo.decide(access_id, new, user.user_id, note)
    if updated is None:
        raise ConflictError("This request has already been decided")
    link = None
    if approve:
        link = await tracking_service.generate_link_for_access(rec["campaign_id"], rec["publisher_id"], user.user_id)
    await audit_record(
        audit_actions.CAMPAIGN_ACCESS_APPROVED if approve else audit_actions.CAMPAIGN_ACCESS_REJECTED,
        actor_user_id=user.user_id,
        metadata={"access_id": access_id, "campaign_id": rec["campaign_id"], "publisher_id": rec["publisher_id"]},
    )
    return {"access": updated, "link": link}
