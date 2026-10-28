"""
Orchestrates OTP creation/sending with resend-cooldown enforcement
(spec §12/§15) on top of the raw storage in db/otp_repository.py.
"""
from app.core.enums import OTPPurpose
from app.core.exceptions import AppError
from app.db import otp_repository
from app.services import email_service
from fastapi import status


class OtpCooldownError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "OTP_COOLDOWN"


_PURPOSE_LABEL = {
    OTPPurpose.EMAIL_VERIFICATION: "email verification",
    OTPPurpose.PASSWORD_RESET: "password reset",
}


async def send_otp(user_id: str, email: str, purpose: OTPPurpose, enforce_cooldown: bool = True) -> None:
    if enforce_cooldown:
        elapsed = await otp_repository.seconds_since_last_sent(user_id, purpose)
        if elapsed is not None and elapsed < otp_repository.RESEND_COOLDOWN_SECONDS:
            raise OtpCooldownError(
                f"Please wait before requesting another code "
                f"({int(otp_repository.RESEND_COOLDOWN_SECONDS - elapsed)}s remaining)."
            )

    code = await otp_repository.create_otp(user_id, purpose)
    label = _PURPOSE_LABEL[purpose]
    if purpose == OTPPurpose.PASSWORD_RESET:
        await email_service.send_password_reset_otp(email, code)
    else:
        await email_service.send_otp(email, code, label)


async def verify_otp(user_id: str, purpose: OTPPurpose, code: str) -> otp_repository.OtpVerifyResult:
    return await otp_repository.verify_otp(user_id, purpose, code)
