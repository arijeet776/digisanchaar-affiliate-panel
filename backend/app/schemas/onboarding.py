from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.auth import _validate_password_strength, validate_publisher_password


class ManagerSignupRequest(BaseModel):
    invite_token: str
    email: EmailStr
    password: str
    display_name: str
    mobile: str | None = Field(default=None, min_length=7, max_length=20, pattern=r"^[0-9+\-\s]+$")

    _validate_password = field_validator("password")(_validate_password_strength)


class PublisherSignupRequest(BaseModel):
    # A manager relationship can only come from the server-side invite. Any
    # extra field (e.g. a tampered manager_id) is refused, not silently ignored.
    model_config = ConfigDict(extra="forbid")

    # Optional since Part 17: public registration needs no invite. An invite
    # (legacy Manager link) may still be supplied; it is validated server-side.
    invite_token: str | None = Field(default=None, max_length=200)
    email: EmailStr
    password: str
    display_name: str = Field(min_length=2, max_length=120)
    mobile: str | None = Field(default=None, min_length=7, max_length=20, pattern=r"^[0-9+\-\s]+$")
    company: str | None = Field(default=None, min_length=1, max_length=120)

    _validate_password = field_validator("password")(validate_publisher_password)


class SignupResponse(BaseModel):
    """Returned right after signup — account is PENDING and unverified; no tokens issued yet."""

    user_id: str
    email: EmailStr
    account_status: str
    message: str = "Signup received. Check your email for a verification code."


class RejectRequest(BaseModel):
    reason: str | None = None


class ApprovePublisherRequest(BaseModel):
    """Optional Manager to assign at approval (Super Admin only). Omitted =>
    approve without a Manager (manager_id stays null)."""

    manager_id: str | None = Field(default=None, max_length=20)


class AssignManagerRequest(BaseModel):
    manager_id: str = Field(min_length=1, max_length=20)
