"""System Settings schemas — tracking-domain configuration (spec §18)."""
from datetime import datetime

from pydantic import BaseModel, Field


class TrackingDomainUpdateRequest(BaseModel):
    tracking_base_url: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=500)


class TrackingDomainConfigResponse(BaseModel):
    configured: bool
    tracking_base_url: str | None
    status: str  # "format_valid" | "not_configured"
    verified: bool
    verified_at: datetime | None
    verification_note: str
    effective_source: str | None  # "database" | "environment" | None
    example_url: str | None  # canonical, server-built — the frontend never constructs one
    created_at: datetime | None
    updated_at: datetime | None
    updated_by: str | None


class AccentThemeUpdateRequest(BaseModel):
    accent_theme: str = Field(min_length=1, max_length=32)


class AccentThemeResponse(BaseModel):
    accent_theme: str  # one of ACCENT_THEMES; defaults to "deep-yellow"
    is_default: bool
    updated_at: datetime | None = None


class WhatsAppGroupUpdateRequest(BaseModel):
    # Empty string / null clears the link.
    whatsapp_group_link: str | None = Field(default=None, max_length=300)


class WhatsAppGroupResponse(BaseModel):
    whatsapp_group_link: str | None = None
    updated_at: datetime | None = None
