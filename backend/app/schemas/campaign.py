"""
Campaign schemas — Part 3 foundation (spec §15 of the Part 3 prompt, plus
the campaign-edit versioning requirement from the follow-up prompt).

Every field listed as "editable" in the campaign-edit spec is represented
here in CampaignEditRequest. Logo is stored as a URL, not a binary upload —
no object-storage service exists yet in this architecture, and inventing
one would be exactly the kind of premature future-Part implementation the
spec repeatedly warns against; a real upload flow is a natural Part 5/8
addition once a storage integration exists.
"""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.enums import (
    ApplyScope, CampaignApprovalMode, CampaignStatus, EventCompletionSource, PauseReasonType, PostbackPlatform,
)


class CampaignEvent(BaseModel):
    event_name: str
    payout: float = Field(ge=0)  # ₹0 is explicitly valid (spec §12 of Part 2 spec, reaffirmed for campaigns)
    completion_source: EventCompletionSource

    @field_validator("event_name")
    @classmethod
    def _non_empty_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("event_name must not be empty")
        return v


class CampaignConfigFields(BaseModel):
    """The full set of fields that make up one versioned campaign configuration."""

    name: str
    advertiser_name: str | None = None
    advertiser_tracking_url: str | None = None
    logo_url: str | None = None
    description: str | None = None
    platform: str | None = None  # free text, spec §9 of Part 1 spec / §15 of Part 3 spec
    postback_platform: PostbackPlatform = PostbackPlatform.CUSTOM
    postback_config: dict = Field(default_factory=dict)
    payout_min: float | None = Field(default=None, ge=0)
    payout_max: float | None = Field(default=None, ge=0)
    daily_cap: int | None = Field(default=None, ge=0)  # None/blank = unlimited (spec §17)
    overall_cap: int | None = Field(default=None, ge=0)  # None/blank = unlimited
    events: list[CampaignEvent] = Field(default_factory=list)
    # Set by Super Admin. PROMOTE_IMMEDIATELY: publishers get their tracking
    # link on request. REQUIRES_APPROVAL: a manager/admin must approve the
    # publisher for this campaign first.
    approval_mode: CampaignApprovalMode = CampaignApprovalMode.PROMOTE_IMMEDIATELY
    # Advertiser's validation window (e.g. 24 / 48 / 72 hours): conversions
    # stay pending until the company's report confirms or rejects them.
    tracking_window_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    # Descriptive/catalogue fields shown to publishers and used for filtering.
    category: str | None = Field(default=None, max_length=60)
    kind: str = Field(default="standard", pattern="^(standard|shopping|survey)$")
    tracking_only: bool = False
    countries: list[str] = Field(default_factory=list, max_length=100)
    # Macro mapping (decided at campaign creation). click_id_param is the
    # advertiser-panel parameter that carries OUR click id outbound (e.g. p1,
    # aff_sub1, click_id) and comes back on the postback. The other three are
    # the parameter names the advertiser's postback uses for its own click id,
    # the campaign title and the event/goal.
    click_id_param: str | None = Field(default=None, max_length=40)
    advertiser_click_id_param: str | None = Field(default=None, max_length=40)
    campaign_title_param: str | None = Field(default=None, max_length=40)
    event_param: str | None = Field(default=None, max_length=40)
    # Optional extra parameters that ALSO carry the same DigiSNR click id outbound
    # (e.g. Trackier wants it in both p1 and source). The postback may bring it
    # back through any of them.
    extra_click_id_params: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("click_id_param", "advertiser_click_id_param", "campaign_title_param", "event_param")
    @classmethod
    def _valid_param_name(cls, v):
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        import re
        if not re.fullmatch(r"[A-Za-z0-9_]{1,40}", v):
            raise ValueError("Parameter names may only contain letters, digits and underscore")
        return v

    @field_validator("extra_click_id_params")
    @classmethod
    def _valid_extra_params(cls, v, info):
        import re
        out: list[str] = []
        taken = {(info.data.get("click_id_param") or "").lower(), (info.data.get("advertiser_click_id_param") or "").lower()}
        taken.discard("")
        for raw in v or []:
            name = (raw or "").strip()
            if not name:
                continue
            if not re.fullmatch(r"[A-Za-z0-9_]{1,40}", name):
                raise ValueError("Parameter names may only contain letters, digits and underscore")
            if name.lower() in {o.lower() for o in out}:
                continue  # same name typed twice
            if name.lower() in taken:
                raise ValueError(f"'{name}' is already used for another click id parameter")
            out.append(name)
        return out

    @field_validator("advertiser_click_id_param")
    @classmethod
    def _adv_param_differs(cls, v, info):
        if v is not None and v.lower() == (info.data.get("click_id_param") or "").lower():
            raise ValueError("Advertiser click id parameter must differ from the parameter carrying the DigiSNR click id")
        return v

    @field_validator("name")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v

    @field_validator("payout_max")
    @classmethod
    def _max_not_below_min(cls, v, info):
        payout_min = info.data.get("payout_min")
        if v is not None and payout_min is not None and v < payout_min:
            raise ValueError("payout_max must not be less than payout_min")
        return v


class CampaignCreateRequest(CampaignConfigFields):
    pass


class CampaignEditRequest(CampaignConfigFields):
    apply_scope: ApplyScope = ApplyScope.FUTURE_ONLY


class PauseCampaignRequest(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _non_empty_reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A pause reason is required")
        return v


class CampaignSummary(BaseModel):
    """List-view projection — no full config, no postback secrets."""

    campaign_id: str
    name: str
    advertiser_name: str | None
    platform: str | None
    status: CampaignStatus
    created_at: datetime
    config_version: int


class CampaignDetail(BaseModel):
    """Detail-view projection — full current config, with postback_config secrets masked."""

    campaign_id: str
    status: CampaignStatus
    status_reason: str | None
    status_reason_type: PauseReasonType | None
    created_at: datetime
    updated_at: datetime
    config_version: int
    config_effective_from: datetime
    config: CampaignConfigFields


class ConfigVersionSummary(BaseModel):
    version: int
    effective_from: datetime
    apply_scope: ApplyScope
    created_by: str
    created_at: datetime
    name: str
