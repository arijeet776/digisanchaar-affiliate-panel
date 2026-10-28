"""
Canonical identity model (spec Sec 3-8, clarified per Part 1 review).

`users` is the ONE authentication/identity record - email, password hash,
role, and account status. It is never duplicated into manager/publisher
profile documents; those hold business data only and link back here by
`user_id`.

    users (canonical identity)
        _id            <- Mongo ObjectId, internal only, never shown to users
        email
        password_hash
        role            <- convenience cache; the DB record here is the
                           authoritative role, see app/core/rbac.py
        account_status
        created_at / updated_at

    managers (business profile)
        manager_id      <- business id e.g. "AM97578", NOT Mongo _id
        user_id         <- FK to users._id
        display_name, ...

    publishers (business profile)
        publisher_id    <- business id e.g. "9778", NOT Mongo _id
        user_id         <- FK to users._id
        display_name, ...

A manager_id/publisher_id is a business identifier for URLs, tracking links,
and reports. It is deliberately never the same value as, or derived from,
the Mongo `_id` (the same distinction the spec makes for click_id).
"""
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.core.enums import AccountStatus, Role

__all__ = ["AccountStatus", "Role", "UserInDB", "UserPublic"]


class UserInDB(BaseModel):
    """Full users-collection document. Internal use only - never returned to a client."""

    id: str  # stringified Mongo _id
    email: EmailStr
    password_hash: str
    role: Role
    account_status: AccountStatus
    email_verified: bool = False
    created_at: datetime
    updated_at: datetime


class UserPublic(BaseModel):
    """Role-safe projection of a user - no password_hash, ever."""

    id: str
    email: EmailStr
    role: Role
    account_status: AccountStatus
    email_verified: bool = False
