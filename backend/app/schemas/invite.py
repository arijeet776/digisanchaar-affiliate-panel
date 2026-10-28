from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.core.enums import Role


class CreateManagerInviteRequest(BaseModel):
    target_email: EmailStr | None = None


class CreatePublisherInviteRequest(BaseModel):
    target_email: EmailStr | None = None
    manager_id: str | None = None  # required if actor is Super Admin; ignored if actor is Manager


class InviteResponse(BaseModel):
    """The raw token is returned ONLY here, at creation time — only its hash is ever stored."""

    invite_token: str
    role: Role
    target_email: EmailStr | None
    manager_id: str | None
    expires_at: datetime
    invitation_type: str | None = None


class InvitePreview(BaseModel):
    """Safe projection for a signup page to check before rendering the form — no token, no hash."""

    valid: bool
    role: Role | None = None
    target_email: EmailStr | None = None
    expires_at: datetime | None = None
