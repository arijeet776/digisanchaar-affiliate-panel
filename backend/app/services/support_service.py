"""
Part 11 — Support ticket workflow.

Scope rules (mirrors the ownership pattern already established in
financial_service.py for Part 9):
- Publisher: may create tickets, and may only see/reply to tickets they
  themselves created. A Publisher can never change a ticket's status —
  the same "requester cannot approve their own request" principle used
  for withdrawals (spec §7: "Publisher must never ... approve own
  withdrawal"); here, a Publisher cannot resolve/close their own ticket.
- Manager: may create tickets, may see/reply to tickets raised by
  themselves OR by any Publisher in their own scope (publisher_id ->
  manager_id, same scope check used everywhere else), and may change
  status on tickets within that scope.
- Super Admin: full visibility, reply, and status-change authority,
  network-wide.
"""
from app.core import audit_actions
from app.core.enums import Role, TicketStatus
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.db import manager_repository, publisher_repository, support_repository
from app.db.audit_repository import record as audit_record

# Valid status transitions. `closed` is terminal — a closed ticket can only be
# reopened by filing a new one (matches "Immutability"/finality patterns used
# elsewhere in the project rather than inventing a separate reopen workflow).
_TRANSITIONS: dict[str, set[str]] = {
    TicketStatus.OPEN.value: {TicketStatus.IN_PROGRESS.value, TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value},
    TicketStatus.IN_PROGRESS.value: {TicketStatus.OPEN.value, TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value},
    TicketStatus.RESOLVED.value: {TicketStatus.IN_PROGRESS.value, TicketStatus.CLOSED.value},
    TicketStatus.CLOSED.value: set(),
}


async def _actor_context(actor_role: Role, actor_user_id: str) -> tuple[str | None, str | None]:
    """Returns (publisher_id, manager_id) for the acting user, or (None, None) for Super Admin."""
    if actor_role == Role.PUBLISHER:
        profile = await publisher_repository.get_publisher_by_user_id(actor_user_id)
        if profile is None:
            raise NotFoundError("Publisher profile not found for current user")
        return profile["publisher_id"], profile["manager_id"]
    if actor_role == Role.MANAGER:
        profile = await manager_repository.get_manager_by_user_id(actor_user_id)
        if profile is None:
            raise NotFoundError("Manager profile not found for current user")
        return None, profile["manager_id"]
    return None, None


def _can_view(ticket: dict, actor_role: Role, actor_user_id: str, actor_manager_id: str | None) -> bool:
    if actor_role == Role.SUPER_ADMIN:
        return True
    if ticket["created_by_user_id"] == actor_user_id:
        return True
    if actor_role == Role.MANAGER and ticket.get("manager_id") == actor_manager_id:
        return True
    return False


async def create_ticket(actor_role: Role, actor_user_id: str, subject: str, category: str, priority: str, message: str) -> dict:
    if actor_role not in (Role.PUBLISHER, Role.MANAGER, Role.SUPER_ADMIN):
        raise ForbiddenError("Not authorized to create a support ticket")
    publisher_id, manager_id = await _actor_context(actor_role, actor_user_id)
    doc = await support_repository.create_ticket(
        created_by_user_id=actor_user_id,
        created_by_role=actor_role.value,
        publisher_id=publisher_id,
        manager_id=manager_id,
        subject=subject,
        category=category,
        priority=priority,
        first_message=message,
    )
    await audit_record(
        audit_actions.SUPPORT_TICKET_CREATED,
        actor_user_id=actor_user_id,
        target_user_id=None,
        metadata={"ticket_id": doc["ticket_id"], "category": category},
    )
    return doc


async def list_tickets(actor_role: Role, actor_user_id: str, status: str | None, page: int, page_size: int):
    skip = (page - 1) * page_size
    if actor_role == Role.SUPER_ADMIN:
        return await support_repository.list_tickets(status, None, None, None, skip, page_size)
    if actor_role == Role.MANAGER:
        profile = await manager_repository.get_manager_by_user_id(actor_user_id)
        if profile is None:
            raise NotFoundError("Manager profile not found for current user")
        scoped_publishers = await publisher_repository.list_publishers_by_manager(profile["manager_id"])
        publisher_ids = [p["publisher_id"] for p in scoped_publishers]
        return await support_repository.list_tickets(status, actor_user_id, profile["manager_id"], publisher_ids, skip, page_size)
    if actor_role == Role.PUBLISHER:
        return await support_repository.list_tickets(status, actor_user_id, None, None, skip, page_size)
    raise ForbiddenError("Not authorized")


async def get_ticket(actor_role: Role, actor_user_id: str, ticket_id: str) -> dict:
    ticket = await support_repository.get_ticket_by_id(ticket_id)
    if ticket is None:
        raise NotFoundError("Ticket not found")
    _, actor_manager_id = await _actor_context(actor_role, actor_user_id)
    if not _can_view(ticket, actor_role, actor_user_id, actor_manager_id):
        raise ForbiddenError("You do not have access to this ticket")
    return ticket


async def add_reply(actor_role: Role, actor_user_id: str, ticket_id: str, body: str) -> dict:
    ticket = await get_ticket(actor_role, actor_user_id, ticket_id)  # raises if out of scope
    updated = await support_repository.add_message(ticket["ticket_id"], actor_user_id, actor_role.value, body)
    await audit_record(
        audit_actions.SUPPORT_TICKET_REPLIED,
        actor_user_id=actor_user_id,
        target_user_id=None,
        metadata={"ticket_id": ticket_id},
    )
    return updated


async def update_status(actor_role: Role, actor_user_id: str, ticket_id: str, new_status: str) -> dict:
    if actor_role == Role.PUBLISHER:
        # A requester never resolves/closes their own ticket — same principle
        # as "Publisher must never ... approve own withdrawal" (spec §7).
        raise ForbiddenError("Publishers cannot change ticket status")
    ticket = await get_ticket(actor_role, actor_user_id, ticket_id)  # raises if out of scope
    before_status = ticket["status"]
    if new_status == before_status:
        raise ConflictError(f"Ticket is already {before_status}")
    if new_status not in _TRANSITIONS.get(before_status, set()):
        raise ConflictError(f"Cannot move a ticket from {before_status} to {new_status}")
    updated = await support_repository.update_status(ticket["ticket_id"], new_status)
    await audit_record(
        audit_actions.SUPPORT_TICKET_STATUS_CHANGED,
        actor_user_id=actor_user_id,
        target_user_id=None,
        before={"status": before_status},
        after={"status": new_status},
        metadata={"ticket_id": ticket_id},
    )
    return updated
