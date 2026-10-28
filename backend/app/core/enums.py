"""
Enums shared across core/ and schemas/. Kept in their own module so
app/core/rbac.py and app/schemas/user.py can both depend on them without
importing each other.

Part 2 addition: REJECTED added to AccountStatus (additive only — PENDING/
ACTIVE/SUSPENDED/DEACTIVATED from Part 1 are unchanged, so no Part 1 code
that switches on those values needs to change). InviteStatus, OTPPurpose,
and OTPStatus are new, Part-2-only enums.
"""
from enum import Enum


class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    MANAGER = "manager"
    PUBLISHER = "publisher"


class AccountStatus(str, Enum):
    PENDING = "pending"          # registered but not fully approved
    ACTIVE = "active"
    REJECTED = "rejected"        # onboarding/application rejected (Part 2)
    SUSPENDED = "suspended"      # temporarily blocked, reversible
    DEACTIVATED = "deactivated"  # permanently closed


class InviteStatus(str, Enum):
    PENDING = "pending"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


class OTPPurpose(str, Enum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class OTPStatus(str, Enum):
    ACTIVE = "active"
    VERIFIED = "verified"
    EXPIRED = "expired"
    MAX_ATTEMPTS = "max_attempts"
    REPLACED = "replaced"


# --- Part 3 (Campaign Management foundation) — new enums only, nothing above changed ---


class CampaignStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"
    # Part 4 foundation (Final Execution Directive §17) — additive. A purged
    # campaign keeps only a tombstone (identity + purge metadata); all its
    # purgeable operational data has been permanently deleted.
    PURGED = "purged"


class CampaignApprovalMode(str, Enum):
    """
    Set by Super Admin at campaign creation/edit. Controls whether a
    publisher can start promoting the moment they see the campaign, or
    must be individually approved first.
    """
    PROMOTE_IMMEDIATELY = "promote_immediately"
    REQUIRES_APPROVAL = "requires_approval"


class CampaignApplicationStatus(str, Enum):
    """Publisher <-> campaign approval record, only created/consulted when
    the campaign's approval_mode is REQUIRES_APPROVAL."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ConversionApprovalStatus(str, Enum):
    """
    Final approval state for a conversion, set from the advertiser's own
    report — separate from the postback's own `status` field (which only
    reflects what the postback claimed at the time it fired). A conversion
    starts PENDING_REPORT regardless of what the postback said, and only
    becomes CONFIRMED/REJECTED once a manager/admin records the
    company's report outcome. Earnings are created on CONFIRMED and
    reversed if a previously-CONFIRMED conversion is later REJECTED
    (chargeback) — never on the postback's own claimed status alone.
    """
    PENDING_REPORT = "pending_report"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class PauseReasonType(str, Enum):
    MANUAL = "manual"
    CAP_REACHED = "cap_reached"


class EventCompletionSource(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"


class PostbackPlatform(str, Enum):
    TRACKIER = "trackier"
    TRACKIX = "trackix"
    OFFER18 = "offer18"
    CUSTOM = "custom"


class ApplyScope(str, Enum):
    """
    Which leads an edited campaign configuration applies to. See
    services/campaign_service.py and docs/ARCHITECTURE.md Part 3 §6 for what
    this does and does NOT do at this stage (no click/conversion engine
    exists yet — Parts 6/7 — so EXISTING_AND_FUTURE has nothing to
    retroactively touch yet; the scope is still recorded for audit/intent).
    """
    FUTURE_ONLY = "future_only"
    EXISTING_AND_FUTURE = "existing_and_future"


class PurgeOperationStatus(str, Enum):
    """Campaign data purge run lifecycle (directive §13)."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class TicketStatus(str, Enum):
    """
    Part 11 — Support ticket lifecycle.

    OPEN -> IN_PROGRESS -> RESOLVED -> CLOSED, or OPEN/IN_PROGRESS -> CLOSED
    directly. Only a Manager or Super Admin may change status (spec parity
    with withdrawals: the requester of a ticket, like the requester of a
    withdrawal, never gets to mark their own request resolved).
    """
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class FraudBlockStatus(str, Enum):
    """
    Blocked-IP registry status (Part 3 fraud foundation). No automatic
    expiry — a record stays BLOCKED until an authorized admin action
    changes it (spec: "no automatic expiry requirement for the admin
    blocked list").
    """
    BLOCKED = "blocked"
    SAFE = "safe"
    PERMANENT_BLOCK = "permanent_block"
