from datetime import datetime

from pydantic import BaseModel, field_validator

from app.core.enums import FraudBlockStatus


class BlockedIpCreateRequest(BaseModel):
    ip_address: str
    block_reason: str
    campaign_id: str | None = None
    publisher_id: str | None = None
    manager_id: str | None = None
    detection_source: str = "manual"

    @field_validator("ip_address", "block_reason")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class BlockedIpRecord(BaseModel):
    id: str
    ip_address: str
    block_reason: str
    campaign_id: str | None
    publisher_id: str | None
    manager_id: str | None
    first_detected_at: datetime
    last_detected_at: datetime
    detection_count: int
    status: FraudBlockStatus
    under_investigation: bool
    detection_source: str
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
