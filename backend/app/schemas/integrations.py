"""Integration hub schemas (Part 10)."""
from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: str = Field(min_length=1, max_length=40)


class ApiKeyCreatedResponse(BaseModel):
    key_id: str
    api_key: str  # shown exactly once — only the hash is stored
    name: str
    scope: str
    created_at: datetime


class ApiKeyListItem(BaseModel):
    key_id: str
    name: str
    prefix: str
    scope: str
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


class WebhookCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=500)
    events: list[str] = Field(min_length=1, max_length=20)


class WebhookListItem(BaseModel):
    webhook_id: str
    name: str
    url: str
    events: list[str]
    enabled: bool
    created_at: datetime


class WebhookCreatedResponse(WebhookListItem):
    secret: str  # shown exactly once — receivers verify X-DigiSNR-Signature with it


class WebhookDeliveryItem(BaseModel):
    delivery_id: str
    webhook_id: str
    event: str
    attempt_count: int
    final_status: str
    created_at: datetime
