"""
Publisher business profile — NOT the identity/auth record (see app/schemas/user.py).
Lives in its own `publishers` collection, linked to `users` by `user_id`.
"""
from datetime import datetime

from pydantic import BaseModel


class PublisherProfile(BaseModel):
    publisher_id: str  # business id, e.g. "9778" — random-looking, never the Mongo _id
    user_id: str  # FK -> users._id
    manager_id: str  # every publisher belongs to exactly one manager
    display_name: str
    created_at: datetime
    updated_at: datetime
