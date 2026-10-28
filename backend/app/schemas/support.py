from pydantic import BaseModel, Field, field_validator

_ALLOWED_CATEGORIES = {"account", "campaign", "tracking", "postback", "payments", "other"}
_ALLOWED_STATUSES = {"open", "in_progress", "resolved", "closed"}
_ALLOWED_PRIORITIES = {"low", "normal", "high"}


class CreateTicketBody(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=3, max_length=5000)
    category: str = "other"
    priority: str = "normal"

    @field_validator("subject", "message")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("This field cannot be empty")
        return v

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        v = (v or "other").strip().lower()
        if v not in _ALLOWED_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(_ALLOWED_CATEGORIES)}")
        return v

    @field_validator("priority")
    @classmethod
    def _valid_priority(cls, v: str) -> str:
        v = (v or "normal").strip().lower()
        if v not in _ALLOWED_PRIORITIES:
            raise ValueError(f"priority must be one of {sorted(_ALLOWED_PRIORITIES)}")
        return v


class ReplyBody(BaseModel):
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("body")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Reply cannot be empty")
        return v


class UpdateStatusBody(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in _ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {sorted(_ALLOWED_STATUSES)}")
        return v
