"""Campaign data purge schemas (directive §6/§11/§12/§14)."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import CampaignStatus


class PurgeCategoryCount(BaseModel):
    collection: str
    label: str
    count: int


class PurgePreviewResponse(BaseModel):
    campaign_id: str
    campaign_name: str
    status: CampaignStatus
    eligible: bool
    eligibility_reason: str | None
    categories: list[PurgeCategoryCount]
    total_purgeable_records: int


class PurgeRequest(BaseModel):
    confirm_campaign_name: str = Field(min_length=1, max_length=200)


class PurgeResultResponse(BaseModel):
    purge_id: str
    status: str  # completed | partial | failed
    campaign_id: str
    campaign_name: str
    deleted_counts: dict[str, int]
    total_deleted: int
    verification: dict
    message: str


class PurgeOperationResponse(BaseModel):
    purge_id: str
    campaign_id: str
    campaign_name: str
    status: str
    actor_user_id: str
    request_id: str | None
    planned_counts: dict[str, int]
    deleted_counts: dict[str, int] | None
    verification: dict | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
