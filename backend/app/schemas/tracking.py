"""Tracking schemas (Part 5) — link management + click responses."""
from datetime import datetime

from pydantic import BaseModel, Field


class TrackingLinkCreateRequest(BaseModel):
    campaign_id: str = Field(min_length=1, max_length=40)
    publisher_id: str = Field(min_length=1, max_length=40)


class TrackingLinkResponse(BaseModel):
    link_id: str
    public_code: str
    campaign_id: str
    campaign_code: str
    campaign_name: str | None
    publisher_id: str
    publisher_code: str
    publisher_name: str | None
    manager_id: str
    status: str
    tracking_url: str | None  # canonical, server-built from the configured domain
    click_count: int
    created_at: datetime
