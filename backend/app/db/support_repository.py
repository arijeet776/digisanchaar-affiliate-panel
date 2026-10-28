"""
Part 11 — Support ticket storage.

support_tickets: {
  ticket_id, subject, category,
  created_by_user_id, created_by_role,
  publisher_id, manager_id,           # ownership/scope fields — see support_service
  status, messages: [{author_user_id, author_role, body, created_at}],
  created_at, updated_at
}

Messages are appended, never edited or removed — a support conversation is
itself a light audit trail of what was said and when, so this collection is
append-oriented for the `messages` array the same way audit_logs is
append-only for its documents.
"""
import logging
import secrets
import string
from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

COLLECTION = "support_tickets"
_MAX_ID_ATTEMPTS = 5


def generate_ticket_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "TICKET-" + "".join(secrets.choice(alphabet) for _ in range(8))


async def create_ticket(
    created_by_user_id: str,
    created_by_role: str,
    publisher_id: str | None,
    manager_id: str | None,
    subject: str,
    category: str,
    priority: str,
    first_message: str,
) -> dict:
    db = get_database()
    now = datetime.now(timezone.utc)
    for _ in range(_MAX_ID_ATTEMPTS):
        ticket_id = generate_ticket_id()
        doc = {
            "ticket_id": ticket_id,
            "subject": subject,
            "category": category,
            "priority": priority,
            "created_by_user_id": created_by_user_id,
            "created_by_role": created_by_role,
            "publisher_id": publisher_id,
            "manager_id": manager_id,
            "status": "open",
            "messages": [
                {
                    "author_user_id": created_by_user_id,
                    "author_role": created_by_role,
                    "body": first_message,
                    "created_at": now,
                }
            ],
            "created_at": now,
            "updated_at": now,
            "resolved_at": None,
            "closed_at": None,
        }
        try:
            await db[COLLECTION].insert_one(doc)
            return doc
        except DuplicateKeyError:
            continue
        except PyMongoError as exc:
            raise ServiceUnavailableError("Could not create support ticket") from exc
    raise ServiceUnavailableError("Could not allocate a unique ticket id")


async def get_ticket_by_id(ticket_id: str) -> dict | None:
    db = get_database()
    try:
        return await db[COLLECTION].find_one({"ticket_id": ticket_id})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Support store unavailable") from exc


async def list_tickets(
    status: str | None,
    created_by_user_id: str | None,
    manager_id: str | None,
    publisher_ids: list[str] | None,
    skip: int,
    limit: int,
) -> tuple[list[dict], int]:
    """
    Scope is expressed by the caller (support_service), not here:
    - Publisher: created_by_user_id = their own user id
    - Manager: manager_id = their own manager_id (covers tickets raised by
      their publishers) OR created_by_user_id = their own user id (tickets
      the manager raised themselves)
    - Super Admin: no scope filters at all
    """
    db = get_database()
    query: dict[str, Any] = {}
    if status:
        query["status"] = status

    scope_clauses = []
    if created_by_user_id:
        scope_clauses.append({"created_by_user_id": created_by_user_id})
    if manager_id:
        scope_clauses.append({"manager_id": manager_id})
    if publisher_ids:
        scope_clauses.append({"publisher_id": {"$in": publisher_ids}})
    if scope_clauses:
        query["$or"] = scope_clauses

    try:
        total = await db[COLLECTION].count_documents(query)
        cursor = db[COLLECTION].find(query).sort("updated_at", -1).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        return items, total
    except PyMongoError as exc:
        raise ServiceUnavailableError("Support store unavailable") from exc


async def add_message(ticket_id: str, author_user_id: str, author_role: str, body: str) -> dict:
    db = get_database()
    now = datetime.now(timezone.utc)
    try:
        doc = await db[COLLECTION].find_one_and_update(
            {"ticket_id": ticket_id},
            {
                "$push": {"messages": {"author_user_id": author_user_id, "author_role": author_role, "body": body, "created_at": now}},
                "$set": {"updated_at": now},
            },
            return_document=ReturnDocument.AFTER,
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Support store unavailable") from exc
    if doc is None:
        raise NotFoundError("Ticket not found")
    return doc


async def update_status(ticket_id: str, status: str) -> dict:
    db = get_database()
    now = datetime.now(timezone.utc)
    update: dict[str, Any] = {"status": status, "updated_at": now}
    # resolved_at/closed_at are set the first time a ticket reaches that state
    # and deliberately left untouched (not cleared) if it's reopened later —
    # so "when was this last resolved/closed" survives a reopen, matching the
    # append-oriented / don't-erase-history spirit used for the ledger in Part 9.
    if status == "resolved":
        update["resolved_at"] = now
    elif status == "closed":
        update["closed_at"] = now
    try:
        doc = await db[COLLECTION].find_one_and_update(
            {"ticket_id": ticket_id},
            {"$set": update},
            return_document=ReturnDocument.AFTER,
        )
    except PyMongoError as exc:
        raise ServiceUnavailableError("Support store unavailable") from exc
    if doc is None:
        raise NotFoundError("Ticket not found")
    return doc


async def count_open() -> int:
    db = get_database()
    try:
        return await db[COLLECTION].count_documents({"status": {"$in": ["open", "in_progress"]}})
    except PyMongoError as exc:
        raise ServiceUnavailableError("Support store unavailable") from exc
