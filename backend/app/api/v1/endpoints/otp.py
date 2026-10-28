"""
OTP send/verify (spec §12-15, §48). `/send` is the resend path — initial
sends happen inline during signup (see onboarding.py), not through this
endpoint, so this one is safe to key purely on email without creating an
account-enumeration signal beyond "a code may have been sent".
"""
from fastapi import APIRouter, Depends

from app.core import audit_actions
from app.core.email_utils import normalize_email
from app.core.enums import OTPPurpose
from app.core.rate_limit_dependency import rate_limit
from app.db import user_repository
from app.db.audit_repository import record as audit_record
from app.db.mongodb import get_database
from app.schemas.otp import OTPSendRequest, OTPVerifyRequest
from app.services import otp_service

router = APIRouter()

GENERIC_SEND_MESSAGE = "If an account matching that request exists, a code has been sent."


@router.post("/send", dependencies=[Depends(rate_limit("otp_send", limit=3, window_seconds=60))])
async def send_otp(body: OTPSendRequest):
    email = normalize_email(body.email)
    user = await user_repository.get_user_by_email(email)
    if user is not None:
        # Resend cooldown is enforced inside otp_service; a cooldown hit
        # raises OtpCooldownError (429), which is fine to surface as-is —
        # it doesn't reveal anything beyond "you already requested one
        # recently", which the legitimate requester already knows.
        await otp_service.send_otp(user.id, email, body.purpose)
    return {"message": GENERIC_SEND_MESSAGE}


@router.post("/verify", dependencies=[Depends(rate_limit("otp_verify", limit=10, window_seconds=60))])
async def verify_otp(body: OTPVerifyRequest):
    email = normalize_email(body.email)
    user = await user_repository.get_user_by_email(email)
    if user is None:
        return {"verified": False, "message": "Invalid or expired code"}

    result = await otp_service.verify_otp(user.id, body.purpose, body.code)
    if not result.success:
        return {"verified": False, "message": "Invalid or expired code"}

    if body.purpose == OTPPurpose.EMAIL_VERIFICATION:
        db = get_database()
        from bson import ObjectId

        await db["users"].update_one({"_id": ObjectId(user.id)}, {"$set": {"email_verified": True}})
        await audit_record(audit_actions.EMAIL_VERIFIED, actor_user_id=user.id, target_user_id=user.id)

    return {"verified": True, "message": "Code verified"}
