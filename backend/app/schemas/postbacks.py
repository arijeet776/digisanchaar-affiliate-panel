"""Postback schemas (Part 6)."""
from datetime import datetime

from pydantic import BaseModel, Field


class PostbackEndpointCreateRequest(BaseModel):
    campaign_id: str = Field(min_length=1, max_length=40)
    platform: str = Field(min_length=1, max_length=40)


class PostbackEndpointSafeResponse(BaseModel):
    endpoint_id: str
    campaign_id: str
    platform: str
    status: str
    received_count: int
    failure_count: int
    last_received_at: datetime | None
    created_at: datetime


class PostbackEndpointCreatedResponse(PostbackEndpointSafeResponse):
    inbound_url: str  # token-bearing URL — returned only at creation time
    advertiser_postback_url: str | None = None  # inbound_url + ?click-id/event/title macros, ready to paste in the advertiser panel


class InboundLogItem(BaseModel):
    postback_id: str
    platform: str
    campaign_id: str
    received_at: datetime
    processing_status: str
    event: str | None
    status: str | None
    digisnr_click_id: str | None
    external_click_id: str | None
    external_conversion_id: str | None
    conversion_id: str | None
    error: str | None


class OutboundLogItem(BaseModel):
    outbound_id: str
    conversion_id: str
    publisher_id: str
    campaign_id: str
    event: str | None
    url: str
    attempt_count: int
    final_status: str
    created_at: datetime
    direction: str = "outbound"
    http_status: int | None = None
    last_error: str | None = None
    attempts: list[dict] = []
    config_scope: str | None = None


class PublisherPostbackConfigRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    campaign_id: str | None = Field(default=None, max_length=40)
    enabled: bool = True


class GlobalPostbackRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    enabled: bool = True
