from app.core import audit_actions
from app.core.enums import FraudBlockStatus
from app.core.exceptions import NotFoundError
from app.db import blocked_ip_repository
from app.db.audit_repository import record as audit_record


def _serialize(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "ip_address": doc["ip_address"],
        "block_reason": doc["block_reason"],
        "campaign_id": doc.get("campaign_id"),
        "publisher_id": doc.get("publisher_id"),
        "manager_id": doc.get("manager_id"),
        "first_detected_at": doc["first_detected_at"],
        "last_detected_at": doc["last_detected_at"],
        "detection_count": doc["detection_count"],
        "status": doc["status"],
        "under_investigation": doc["under_investigation"],
        "detection_source": doc["detection_source"],
        "created_by": doc["created_by"],
        "updated_by": doc["updated_by"],
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
    }


async def register_blocked_ip(actor_user_id: str, body) -> dict:
    doc = await blocked_ip_repository.create_or_bump(
        ip_address=body.ip_address,
        block_reason=body.block_reason,
        campaign_id=body.campaign_id,
        publisher_id=body.publisher_id,
        manager_id=body.manager_id,
        detection_source=body.detection_source,
        actor_user_id=actor_user_id,
    )
    await audit_record(
        audit_actions.BLOCKED_IP_CREATED, actor_user_id=actor_user_id,
        after={"ip_address": body.ip_address, "status": "blocked"},
        metadata={"blocked_ip_id": str(doc["_id"]), "detection_count": doc["detection_count"]},
    )
    return _serialize(doc)


async def get_blocked_ip(record_id: str) -> dict:
    doc = await blocked_ip_repository.get_by_id(record_id)
    if doc is None:
        raise NotFoundError("Blocked IP record not found")
    return _serialize(doc)


async def list_blocked_ips(status: FraudBlockStatus | None, search: str | None, skip: int, limit: int):
    items, total = await blocked_ip_repository.list_blocked_ips(status, search, skip, limit)
    return [_serialize(i) for i in items], total


async def mark_safe(record_id: str, actor_user_id: str) -> dict:
    doc = await blocked_ip_repository.get_by_id(record_id)
    if doc is None:
        raise NotFoundError("Blocked IP record not found")
    updated = await blocked_ip_repository.update_status(record_id, FraudBlockStatus.SAFE, actor_user_id)
    await audit_record(
        audit_actions.BLOCKED_IP_MARKED_SAFE, actor_user_id=actor_user_id,
        before={"status": doc["status"]}, after={"status": "safe"},
        metadata={"blocked_ip_id": record_id},
    )
    return _serialize(updated)


async def keep_blocked(record_id: str, actor_user_id: str) -> dict:
    doc = await blocked_ip_repository.get_by_id(record_id)
    if doc is None:
        raise NotFoundError("Blocked IP record not found")
    # No status change — this records an explicit admin review decision.
    await audit_record(
        audit_actions.BLOCKED_IP_KEPT_BLOCKED, actor_user_id=actor_user_id,
        before={"status": doc["status"]}, after={"status": doc["status"]},
        metadata={"blocked_ip_id": record_id},
    )
    return _serialize(doc)


async def permanent_block(record_id: str, actor_user_id: str) -> dict:
    doc = await blocked_ip_repository.get_by_id(record_id)
    if doc is None:
        raise NotFoundError("Blocked IP record not found")
    updated = await blocked_ip_repository.update_status(record_id, FraudBlockStatus.PERMANENT_BLOCK, actor_user_id)
    await audit_record(
        audit_actions.BLOCKED_IP_PERMANENT_BLOCK, actor_user_id=actor_user_id,
        before={"status": doc["status"]}, after={"status": "permanent_block"},
        metadata={"blocked_ip_id": record_id},
    )
    return _serialize(updated)


async def set_investigation(record_id: str, flag: bool, actor_user_id: str) -> dict:
    doc = await blocked_ip_repository.get_by_id(record_id)
    if doc is None:
        raise NotFoundError("Blocked IP record not found")
    updated = await blocked_ip_repository.set_investigation_flag(record_id, flag, actor_user_id)
    await audit_record(
        audit_actions.BLOCKED_IP_INVESTIGATION_TOGGLED, actor_user_id=actor_user_id,
        before={"under_investigation": doc["under_investigation"]}, after={"under_investigation": flag},
        metadata={"blocked_ip_id": record_id},
    )
    return _serialize(updated)


async def get_overview() -> dict:
    return {
        "blocked": await blocked_ip_repository.count_by_status(FraudBlockStatus.BLOCKED),
        "permanent_block": await blocked_ip_repository.count_by_status(FraudBlockStatus.PERMANENT_BLOCK),
        "safe": await blocked_ip_repository.count_by_status(FraudBlockStatus.SAFE),
        "under_investigation": await blocked_ip_repository.count_under_investigation(),
    }
