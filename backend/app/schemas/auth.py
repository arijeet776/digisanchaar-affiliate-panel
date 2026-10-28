from pydantic import BaseModel, EmailStr, field_validator

MIN_PASSWORD_LENGTH = 8


def _validate_password_strength(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    return value


PUBLISHER_MIN_LETTERS = 5
_SPECIALS = set("!@#$%^&*()_+-=[]{}|;:'\",.<>/?`~\\")


def password_rule_results(value: str) -> dict[str, bool]:
    """Single source of truth for the public Publisher registration policy
    (mirrored 1:1 by the live indicator in the frontend)."""
    letters = sum(1 for ch in value if ch.isalpha())
    return {
        "letters": letters >= PUBLISHER_MIN_LETTERS,
        "uppercase": any(ch.isupper() for ch in value),
        "number": any(ch.isdigit() for ch in value),
        "special": any((not ch.isalnum()) and (not ch.isspace()) for ch in value),
    }


def validate_publisher_password(value: str) -> str:
    """>= 5 alphabetic letters, >= 1 uppercase, >= 1 number, >= 1 special.
    Enforced server-side independently of the frontend."""
    if len(value) > 128:
        raise ValueError("Password is too long")
    r = password_rule_results(value)
    missing = []
    if not r["letters"]:
        missing.append(f"at least {PUBLISHER_MIN_LETTERS} letters")
    if not r["uppercase"]:
        missing.append("1 uppercase letter")
    if not r["number"]:
        missing.append("1 number")
    if not r["special"]:
        missing.append("1 special character")
    if missing:
        raise ValueError("Password must contain " + ", ".join(missing))
    return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp_code: str
    new_password: str

    _validate_new_password = field_validator("new_password")(_validate_password_strength)
