from pydantic import BaseModel, EmailStr

from app.core.enums import OTPPurpose


class OTPSendRequest(BaseModel):
    email: EmailStr
    purpose: OTPPurpose


class OTPVerifyRequest(BaseModel):
    email: EmailStr
    purpose: OTPPurpose
    code: str
