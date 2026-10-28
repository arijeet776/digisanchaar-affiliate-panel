"""
Canonical email normalization (spec §5): trim + lowercase, applied
identically at signup, login, OTP, password reset, and invite lookups.
Never call str.strip().lower() ad hoc elsewhere — always go through this.
"""


def normalize_email(email: str) -> str:
    return email.strip().lower()
