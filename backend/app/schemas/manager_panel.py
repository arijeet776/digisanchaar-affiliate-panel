"""Manager Panel schemas (Part 4, spec §49).

Managers may see permitted advertiser rates (spec §6) but NEVER internal
identifiers beyond their own scope, and never the advertiser's tracking URL
(sensitive minimization — publishers never see it either).
"""
from datetime import datetime

from pydantic import BaseModel


class ManagerMeResponse(BaseModel):
    user_id: str
    manager_id: str
    display_name: str
    email: str | None
    mobile: str | None = None


class ManagerPublisherKpis(BaseModel):
    total: int
    active: int
    pending: int
    rejected: int


class UnavailableMetric(BaseModel):
    """Honest placeholder — never a fabricated number."""

    available: bool = False
    value: int | None = None
    reason: str


class ManagerDashboardResponse(BaseModel):
    manager_id: str
    display_name: str
    publishers: ManagerPublisherKpis
    available_campaigns: int
    clicks: UnavailableMetric
    conversions: UnavailableMetric
    earnings: UnavailableMetric


class ManagerCampaignEvent(BaseModel):
    event_name: str
    payout: float
    completion_source: str


class ManagerCampaignListItem(BaseModel):
    campaign_id: str
    name: str
    status: str
    advertiser_name: str | None
    platform: str | None
    payout_min: float | None
    payout_max: float | None
    events: list[ManagerCampaignEvent]
    daily_cap: int | None
    overall_cap: int | None


class ManagerCampaignDetail(ManagerCampaignListItem):
    description: str | None
    instructions: str | None
    postback_platform: str | None
    created_at: datetime
