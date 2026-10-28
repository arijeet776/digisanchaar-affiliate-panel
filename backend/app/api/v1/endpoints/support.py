"""
Part 11 — Support ticket endpoints. Shared across all three roles (unlike
wallet.py/admin_financials.py's split), because scope is expressed inside
support_service per-call rather than by splitting into a separate
"my tickets" vs "admin tickets" router — every role hits the same routes
and support_service enforces who can see/do what.
"""
from fastapi import APIRouter, Depends, Query

from app.core.enums import Role
from app.core.rbac import CurrentUser, require_role
from app.schemas.support import CreateTicketBody, ReplyBody, UpdateStatusBody
from app.db import manager_repository, publisher_repository
from app.services import settings_service, support_service

router = APIRouter()

_any_role = require_role(Role.SUPER_ADMIN, Role.MANAGER, Role.PUBLISHER)


@router.post("/tickets")
async def create_ticket(body: CreateTicketBody, user: CurrentUser = Depends(_any_role)):
    doc = await support_service.create_ticket(user.role, user.user_id, body.subject, body.category, body.priority, body.message)
    return _serialize(doc)


@router.get("/tickets")
async def list_tickets(
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(_any_role),
):
    items, total = await support_service.list_tickets(user.role, user.user_id, status, page, page_size)
    return {"items": [_serialize(t) for t in items], "total": total, "page": page, "page_size": page_size}


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, user: CurrentUser = Depends(_any_role)):
    doc = await support_service.get_ticket(user.role, user.user_id, ticket_id)
    return _serialize(doc)


@router.post("/tickets/{ticket_id}/reply")
async def reply_to_ticket(ticket_id: str, body: ReplyBody, user: CurrentUser = Depends(_any_role)):
    doc = await support_service.add_reply(user.role, user.user_id, ticket_id, body.body)
    return _serialize(doc)


@router.post("/tickets/{ticket_id}/status")
async def update_ticket_status(ticket_id: str, body: UpdateStatusBody, user: CurrentUser = Depends(_any_role)):
    doc = await support_service.update_status(user.role, user.user_id, ticket_id, body.status)
    return _serialize(doc)


def _serialize(t: dict) -> dict:
    def _iso(v):
        return v.isoformat() if hasattr(v, "isoformat") else v

    return {
        "ticket_id": t["ticket_id"],
        "subject": t["subject"],
        "category": t["category"],
        "priority": t.get("priority", "normal"),
        "status": t["status"],
        "created_by_user_id": t["created_by_user_id"],
        "created_by_role": t["created_by_role"],
        "publisher_id": t.get("publisher_id"),
        "manager_id": t.get("manager_id"),
        "messages": [
            {
                "author_user_id": m["author_user_id"],
                "author_role": m["author_role"],
                "body": m["body"],
                "created_at": _iso(m["created_at"]),
            }
            for m in t.get("messages", [])
        ],
        "created_at": _iso(t["created_at"]),
        "updated_at": _iso(t["updated_at"]),
        "resolved_at": _iso(t.get("resolved_at")),
        "closed_at": _iso(t.get("closed_at")),
    }


@router.get("/contact")
async def support_contact(user: CurrentUser = Depends(_any_role)):
    """Real support contact data: the caller's assigned Manager (publishers
    only) and the Super Admin-configured WhatsApp group. Nothing hardcoded;
    absent values come back as null so the UI shows a proper empty state."""
    manager = None
    if user.role == Role.PUBLISHER:
        profile = await publisher_repository.get_publisher_by_user_id(user.user_id)
        if profile and profile.get("manager_id"):
            m = await manager_repository.get_manager_by_manager_id(profile["manager_id"])
            if m:
                manager = {"name": m["display_name"], "mobile": m.get("mobile")}
    wa = await settings_service.get_whatsapp_group_link()
    return {"manager": manager, "whatsapp_group_link": wa["whatsapp_group_link"]}
