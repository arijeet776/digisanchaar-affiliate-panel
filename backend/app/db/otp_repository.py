"""
OTP storage. Codes are hashed with the same bcrypt context used for
passwords (never stored in plaintext); we look records up by
user_id + purpose + status, then verify the hash — we never need to look
up "by code", so bcrypt's non-determinism is not a problem here the way it
would be for invite tokens (see core/security.py's hash_token for that
case).
"""
import logging
from datetime import datetime, timedelta, timezone

from pymongo.errors import PyMongoError

from app.core.enums import OTPPurpose, OTPStatus
from app.core.exceptions import ServiceUnavailableError
from app.core.security import generate_numeric_otp, hash_password, verify_password
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

COLLECTION = "otps"

OTP_TTL_MINUTES = 10
MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60


async def get_active_otp(user_id: str, purpose: OTPPurpose) -> dict | None:
    db = get_database()
    try:
        return await db[COLLECTION].find_one(
            {"user_id": user_id, "purpose": purpose.value, "status": OTPStatus.ACTIVE.value},
            sort=[("created_at", -1)],
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("OTP store unavailable") from exc


async def seconds_since_last_sent(user_id: str, purpose: OTPPurpose) -> float | None:
    db = get_database()
    try:
        latest = await db[COLLECTION].find_one(
            {"user_id": user_id, "purpose": purpose.value}, sort=[("created_at", -1)]
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("OTP store unavailable") from exc

    if latest is None:
        return None
    created_at = latest["created_at"]
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created_at).total_seconds()


async def create_otp(user_id: str, purpose: OTPPurpose) -> str:
    """
    Invalidates any prior ACTIVE otp for this user+purpose (spec: "old OTP
    invalidation when a new OTP is issued"), then creates a new one.
    Returns the RAW code — caller is responsible for sending it and must
    never persist or log it in production.
    """
    db = get_database()
    now = datetime.now(timezone.utc)

    try:
        await db[COLLECTION].update_many(
            {"user_id": user_id, "purpose": purpose.value, "status": OTPStatus.ACTIVE.value},
            {"$set": {"status": OTPStatus.REPLACED.value}},
        )

        code = generate_numeric_otp()
        await db[COLLECTION].insert_one(
            {
                "user_id": user_id,
                "purpose": purpose.value,
                "code_hash": hash_password(code),
                "status": OTPStatus.ACTIVE.value,
                "attempts": 0,
                "max_attempts": MAX_ATTEMPTS,
                "created_at": now,
                "expires_at": now + timedelta(minutes=OTP_TTL_MINUTES),
            }
        )
    except PyMongoError as exc:
        logger.error("Failed to create OTP: %s", exc)
        raise ServiceUnavailableError("OTP store unavailable") from exc

    return code


class OtpVerifyResult:
    def __init__(self, success: bool, reason: str | None = None):
        self.success = success
        self.reason = reason  # "not_found" | "expired" | "max_attempts" | "invalid_code"


async def verify_otp(user_id: str, purpose: OTPPurpose, code: str) -> OtpVerifyResult:
    db = get_database()
    try:
        otp = await get_active_otp(user_id, purpose)
        if otp is None:
            return OtpVerifyResult(False, "not_found")

        expires_at = otp["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            await db[COLLECTION].update_one(
                {"_id": otp["_id"]}, {"$set": {"status": OTPStatus.EXPIRED.value}}
            )
            return OtpVerifyResult(False, "expired")

        if otp["attempts"] >= otp["max_attempts"]:
            await db[COLLECTION].update_one(
                {"_id": otp["_id"]}, {"$set": {"status": OTPStatus.MAX_ATTEMPTS.value}}
            )
            return OtpVerifyResult(False, "max_attempts")

        if not verify_password(code, otp["code_hash"]):
            new_attempts = otp["attempts"] + 1
            update = {"attempts": new_attempts}
            if new_attempts >= otp["max_attempts"]:
                update["status"] = OTPStatus.MAX_ATTEMPTS.value
            await db[COLLECTION].update_one({"_id": otp["_id"]}, {"$set": update})
            return OtpVerifyResult(False, "invalid_code")

        # Success: one-time use — mark verified so it can never be replayed.
        await db[COLLECTION].update_one(
            {"_id": otp["_id"]}, {"$set": {"status": OTPStatus.VERIFIED.value}}
        )
        return OtpVerifyResult(True)
    except PyMongoError as exc:
        raise ServiceUnavailableError("OTP store unavailable") from exc
