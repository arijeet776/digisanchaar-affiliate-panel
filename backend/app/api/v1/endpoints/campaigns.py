"""
Campaign management endpoints — Super Admin only in Part 3 (Manager-side
campaign visibility is Part 4 territory). CRUD + lifecycle only; no
tracking/conversion/postback engine here (Parts 6/7).
"""
from fastapi import APIRouter, Depends, Query, Response

from app.core.enums import CampaignStatus, Role
from app.core.masking import mask_secret_fields
from app.core.rbac import CurrentUser, require_role
from app.schemas.campaign import (
    CampaignCreateRequest,
    CampaignDetail,
    CampaignEditRequest,
    CampaignSummary,
    ConfigVersionSummary,
    PauseCampaignRequest,
)
from app.services import campaign_service

router = APIRouter()

_super_admin_only = require_role(Role.SUPER_ADMIN)


def _to_detail(campaign_doc: dict, version_doc: dict) -> CampaignDetail:
    config = {k: v for k, v in version_doc.items() if k not in ("_id", "campaign_id", "version", "effective_from", "apply_scope", "created_by", "created_at")}
    config["postback_config"] = mask_secret_fields(config.get("postback_config", {}) or {})
    return CampaignDetail(
        campaign_id=campaign_doc["campaign_id"],
        status=CampaignStatus(campaign_doc["status"]),
        status_reason=campaign_doc.get("status_reason"),
        status_reason_type=campaign_doc.get("status_reason_type"),
        created_at=campaign_doc["created_at"],
        updated_at=campaign_doc["updated_at"],
        config_version=version_doc["version"],
        config_effective_from=version_doc["effective_from"],
        config=config,
    )


@router.post("", response_model=CampaignDetail)
async def create_campaign(body: CampaignCreateRequest, user: CurrentUser = Depends(_super_admin_only)):
    campaign_doc = await campaign_service.create_campaign(user.user_id, body)
    detail_pair = await campaign_service.get_campaign_detail(campaign_doc["campaign_id"])
    return _to_detail(*detail_pair)


@router.get("")
async def list_campaigns(
    response: Response,
    status: CampaignStatus | None = None,
    platform: str | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(_super_admin_only),
):
    from app.db import campaign_repository

    skip = (page - 1) * page_size
    items, total = await campaign_repository.list_campaigns(status, platform, search, skip, page_size)
    response.headers["X-Total-Count"] = str(total)
    return [
        CampaignSummary(
            campaign_id=c["campaign_id"],
            name=c["summary"]["name"],
            advertiser_name=c["summary"].get("advertiser_name"),
            platform=c["summary"].get("platform"),
            status=CampaignStatus(c["status"]),
            created_at=c["created_at"],
            config_version=c["current_config_version"],
        )
        for c in items
    ]


@router.get("/{campaign_id}", response_model=CampaignDetail)
async def get_campaign(campaign_id: str, user: CurrentUser = Depends(_super_admin_only)):
    campaign_doc, version_doc = await campaign_service.get_campaign_detail(campaign_id)
    return _to_detail(campaign_doc, version_doc)


@router.get("/{campaign_id}/history", response_model=list[ConfigVersionSummary])
async def get_campaign_history(campaign_id: str, user: CurrentUser = Depends(_super_admin_only)):
    versions = await campaign_service.list_config_history(campaign_id)
    return [
        ConfigVersionSummary(
            version=v["version"], effective_from=v["effective_from"], apply_scope=v["apply_scope"],
            created_by=v["created_by"], created_at=v["created_at"], name=v["name"],
        )
        for v in versions
    ]


@router.patch("/{campaign_id}", response_model=CampaignDetail)
async def edit_campaign(campaign_id: str, body: CampaignEditRequest, user: CurrentUser = Depends(_super_admin_only)):
    await campaign_service.edit_campaign(campaign_id, user.user_id, body)
    campaign_doc, version_doc = await campaign_service.get_campaign_detail(campaign_id)
    return _to_detail(campaign_doc, version_doc)


@router.post("/{campaign_id}/activate", response_model=CampaignDetail)
async def activate_campaign(campaign_id: str, user: CurrentUser = Depends(_super_admin_only)):
    await campaign_service.activate_campaign(campaign_id, user.user_id)
    campaign_doc, version_doc = await campaign_service.get_campaign_detail(campaign_id)
    return _to_detail(campaign_doc, version_doc)


@router.post("/{campaign_id}/pause", response_model=CampaignDetail)
async def pause_campaign(campaign_id: str, body: PauseCampaignRequest, user: CurrentUser = Depends(_super_admin_only)):
    await campaign_service.pause_campaign(campaign_id, user.user_id, body.reason)
    campaign_doc, version_doc = await campaign_service.get_campaign_detail(campaign_id)
    return _to_detail(campaign_doc, version_doc)


@router.post("/{campaign_id}/resume", response_model=CampaignDetail)
async def resume_campaign(campaign_id: str, user: CurrentUser = Depends(_super_admin_only)):
    await campaign_service.resume_campaign(campaign_id, user.user_id)
    campaign_doc, version_doc = await campaign_service.get_campaign_detail(campaign_id)
    return _to_detail(campaign_doc, version_doc)


@router.post("/{campaign_id}/end", response_model=CampaignDetail)
async def end_campaign(campaign_id: str, user: CurrentUser = Depends(_super_admin_only)):
    await campaign_service.end_campaign(campaign_id, user.user_id)
    campaign_doc, version_doc = await campaign_service.get_campaign_detail(campaign_id)
    return _to_detail(campaign_doc, version_doc)
