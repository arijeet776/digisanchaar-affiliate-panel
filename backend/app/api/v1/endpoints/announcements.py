"""Broadcast messages: Super Admin writes / removes, Manager + Publisher read."""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.enums import Role
from app.core.rbac import CurrentUser, require_role
from app.services import announcement_service as svc

router = APIRouter()
_any_role = require_role(Role.SUPER_ADMIN, Role.MANAGER, Role.PUBLISHER)
_super_admin = require_role(Role.SUPER_ADMIN)


class AnnouncementBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=2000)
    audience: Literal["all", "managers", "publishers"] = "all"


@router.get("")
async def list_announcements(user: CurrentUser = Depends(_any_role)):
    return {"items": await svc.list_for(user.role)}


@router.post("")
async def create_announcement(body: AnnouncementBody, user: CurrentUser = Depends(_super_admin)):
    return await svc.create(user.user_id, body.title, body.message, body.audience)


@router.delete("/{announcement_id}")
async def delete_announcement(announcement_id: str, user: CurrentUser = Depends(_super_admin)):
    await svc.remove(user.user_id, announcement_id)
    return {"deleted": True}
