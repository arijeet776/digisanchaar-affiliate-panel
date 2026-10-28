"""
Campaign business logic — Part 3 foundation.

IMPORTANT SCOPE BOUNDARY (documented here because it's the single most
load-bearing decision in this file): `edit_campaign`'s `apply_scope`
parameter is fully implemented and tested at the CONFIGURATION layer —
every edit creates a new, immutable, appended `campaign_config_versions`
document; nothing is ever overwritten; the full version history stays
queryable forever. What it does NOT do yet is retroactively touch any
existing click/conversion/lead records when `EXISTING_AND_FUTURE` is
chosen, because no click/conversion/lead data model exists yet — that's
Parts 6/7. `count_existing_affected_records` always returns 0 today and
says so in its own docstring; the API is honest about this rather than
fabricating a number. When Parts 6/7 introduce lead records, they will
read `campaign_config_versions` by `effective_from` to resolve "which
config applied to this lead" — the version history this module already
builds correctly is exactly what makes that possible later without needing
a redesign now.
"""
from app.core.enums import ApplyScope, CampaignStatus, PauseReasonType
from app.core.exceptions import ConflictError, NotFoundError
from app.db import campaign_repository
from app.db.audit_repository import record as audit_record
from app.core import audit_actions


class AlreadyProcessedError(ConflictError):
    code = "ALREADY_PROCESSED"


def _fields_dict(fields_model) -> dict:
    data = fields_model.model_dump()
    data["events"] = [e if isinstance(e, dict) else e for e in data.get("events", [])]
    return data


async def create_campaign(actor_user_id: str, fields_model) -> dict:
    fields = _fields_dict(fields_model)
    campaign_doc, version_doc = await campaign_repository.create_campaign(actor_user_id, fields)
    await audit_record(
        audit_actions.CAMPAIGN_CREATED, actor_user_id=actor_user_id,
        target_user_id=None, after={"campaign_id": campaign_doc["campaign_id"], "name": fields["name"]},
        metadata={"campaign_id": campaign_doc["campaign_id"]},
    )
    return campaign_doc


async def get_campaign_detail(campaign_id: str) -> tuple[dict, dict]:
    campaign_doc = await campaign_repository.get_campaign(campaign_id)
    if campaign_doc is None:
        raise NotFoundError("Campaign not found")
    version_doc = await campaign_repository.get_current_config(campaign_doc)
    return campaign_doc, version_doc


async def list_config_history(campaign_id: str) -> list[dict]:
    campaign_doc = await campaign_repository.get_campaign(campaign_id)
    if campaign_doc is None:
        raise NotFoundError("Campaign not found")
    return await campaign_repository.list_config_versions(campaign_id)


async def edit_campaign(campaign_id: str, actor_user_id: str, edit_model) -> dict:
    campaign_doc = await campaign_repository.get_campaign(campaign_id)
    if campaign_doc is None:
        raise NotFoundError("Campaign not found")

    apply_scope = edit_model.apply_scope
    fields = _fields_dict(edit_model)
    fields.pop("apply_scope", None)

    new_version = await campaign_repository.create_new_version(campaign_id, fields, apply_scope, actor_user_id)

    affected = 0
    if apply_scope == ApplyScope.EXISTING_AND_FUTURE:
        affected = await count_existing_affected_records(campaign_id)

    await audit_record(
        audit_actions.CAMPAIGN_UPDATED, actor_user_id=actor_user_id,
        target_user_id=None,
        before={"version": campaign_doc["current_config_version"]},
        after={"version": new_version["version"], "apply_scope": apply_scope.value},
        metadata={"campaign_id": campaign_id, "existing_records_affected": affected},
    )
    return new_version


async def count_existing_affected_records(campaign_id: str) -> int:
    """
    Always 0 in Part 3: no click/conversion/lead collection exists yet
    (Parts 6/7 build that data model). This function exists now as the
    integration point those later parts will implement against, so the
    `EXISTING_AND_FUTURE` API contract doesn't need to change shape later —
    only this function's body does.
    """
    return 0


async def _transition(
    campaign_id: str, actor_user_id: str, from_statuses: list[CampaignStatus], to_status: CampaignStatus,
    action: str, reason: str | None = None, reason_type: PauseReasonType | None = None,
) -> dict:
    campaign_doc = await campaign_repository.get_campaign(campaign_id)
    if campaign_doc is None:
        raise NotFoundError("Campaign not found")

    updated = await campaign_repository.atomic_status_transition(
        campaign_id, from_statuses, to_status, reason, reason_type
    )
    if updated is None:
        raise AlreadyProcessedError(
            f"Campaign is not in a state that allows this transition (current status: {campaign_doc['status']})"
        )

    await audit_record(
        action, actor_user_id=actor_user_id, target_user_id=None,
        before={"status": campaign_doc["status"]}, after={"status": to_status.value}, reason=reason,
        metadata={"campaign_id": campaign_id},
    )
    return updated


async def activate_campaign(campaign_id: str, actor_user_id: str) -> dict:
    return await _transition(
        campaign_id, actor_user_id, [CampaignStatus.DRAFT], CampaignStatus.ACTIVE, audit_actions.CAMPAIGN_ACTIVATED
    )


async def pause_campaign(campaign_id: str, actor_user_id: str, reason: str) -> dict:
    return await _transition(
        campaign_id, actor_user_id, [CampaignStatus.ACTIVE], CampaignStatus.PAUSED, audit_actions.CAMPAIGN_PAUSED,
        reason=reason, reason_type=PauseReasonType.MANUAL,
    )


async def resume_campaign(campaign_id: str, actor_user_id: str) -> dict:
    return await _transition(
        campaign_id, actor_user_id, [CampaignStatus.PAUSED], CampaignStatus.ACTIVE, audit_actions.CAMPAIGN_RESUMED,
        reason=None, reason_type=None,
    )


async def end_campaign(campaign_id: str, actor_user_id: str) -> dict:
    return await _transition(
        campaign_id, actor_user_id,
        [CampaignStatus.DRAFT, CampaignStatus.ACTIVE, CampaignStatus.PAUSED], CampaignStatus.ENDED,
        audit_actions.CAMPAIGN_ENDED,
    )


def assert_campaign_is_traffic_live(campaign_doc: dict) -> None:
    """
    The Part 5 tracking engine MUST call this before (a) generating a new
    tracking link and (b) creating a new click/attribution record.

    Only ACTIVE campaigns are traffic-live (spec §13/§16): draft, paused and
    ended campaigns must not produce new links or clicks, and a PURGED
    campaign (directive §16-17) must reject old tracking requests outright —
    its tombstone exists precisely so this check keeps working after the
    operational data is gone. Late postbacks for already-existing clicks are
    a separate conversion path (spec §13) and are NOT gated by this.
    """
    if CampaignStatus(campaign_doc["status"]) != CampaignStatus.ACTIVE:
        raise ConflictError(
            f"Campaign is {campaign_doc['status']} — not accepting new tracking activity"
        )
