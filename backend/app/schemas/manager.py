"""
Manager business profile — NOT the identity/auth record (see app/schemas/user.py).
Lives in its own `managers` collection, linked to `users` by `user_id`.
"""
from datetime import datetime

from pydantic import BaseModel


class ManagerProfile(BaseModel):
    manager_id: str  # business id, e.g. "AM97578" — never the Mongo _id
    user_id: str  # FK -> users._id
    display_name: str
    created_at: datetime
    updated_at: datetime
