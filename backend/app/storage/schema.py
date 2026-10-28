"""
Single source of truth for the storage schema (the Supabase SQL is generated from it).

Derived from the persistent entities the application ACTUALLY uses today
(see db/mongodb.py::ensure_indexes, every repository, and the Postgres
migrations 001/002). Nothing here is invented: where a name differs from the
collection/table it is only a human-friendly tab title.

backend/tools/generate_supabase_sql.py renders this structure into
migrations/supabase/001_schema.sql.

Column types:  s=text  i=integer  f=float  b=boolean  d=datetime (ISO-8601 UTC
text, lexicographically sortable)  m=money (2dp text, summed as integer paise)
j=JSON text (nested objects/arrays).  Every table also has `_extra` (JSON):
any field a document carries that is not a declared column is preserved there,
so no data is ever lost when the application adds a field.
"""
from __future__ import annotations

CORE, TRACKING, FINANCE = "core", "tracking", "finance"

DB_TITLES = {CORE: "DigiSanchaar Core Database", TRACKING: "DigiSanchaar Tracking & Operations", FINANCE: "DigiSanchaar Finance"}


def _cols(spec: str) -> list[list[str]]:
    out = []
    for part in spec.split():
        name, _, typ = part.partition(":")
        out.append([name, typ or "s"])
    return out


def _t(db, tab, collection, spec, *, unique=(), ordered_by=None, append_only=False, autoinc=None, id_field="_id"):
    cols = _cols(spec)
    if id_field == "_id":
        cols = [["_id", "s"]] + cols
    if autoinc:
        cols = [[autoinc, "i"]] + cols
    cols.append(["_extra", "j"])
    return {
        "db": db, "tab": tab, "collection": collection, "columns": cols,
        "unique": [list(u) for u in unique], "ordered_by": ordered_by,
        "append_only": append_only, "autoinc": autoinc, "id_field": id_field,
    }


TABLES: list[dict] = [
    # ------------------------------------------------------------- CORE ----
    _t(CORE, "Users", "users",
       "email role account_status email_verified:b password_hash created_at:d updated_at:d",
       unique=[["email"]]),
    _t(CORE, "Managers", "managers",
       "manager_id user_id display_name mobile created_at:d updated_at:d",
       unique=[["manager_id"], ["user_id"]]),
    _t(CORE, "Publishers", "publishers",
       "publisher_id user_id manager_id display_name mobile company invitation_type invited_by invite_id created_at:d updated_at:d",
       unique=[["publisher_id"], ["user_id"]]),
    _t(CORE, "Campaigns", "campaigns",
       "campaign_id status status_reason status_reason_type current_config_version:i summary:j created_by created_at:d updated_at:d",
       unique=[["campaign_id"]]),
    # Campaign events (event name + payouts) live inside each config version.
    _t(CORE, "CampaignConfigVersions", "campaign_config_versions",
       "campaign_id version:i effective_from:d apply_scope created_by created_at:d name advertiser_name platform events:j",
       unique=[["campaign_id", "version"]]),
    # "Applications": a publisher's request to run a campaign.
    _t(CORE, "CampaignAccess", "campaign_access",
       "access_id campaign_id publisher_id manager_id status requested_at:d decided_at:d decided_by note",
       unique=[["access_id"], ["campaign_id", "publisher_id"]]),
    _t(CORE, "Invites", "invites",
       "token_hash role target_email manager_id invitation_type created_by status created_at:d expires_at:d used_at:d revoked_at:d",
       unique=[["token_hash"]]),
    _t(CORE, "Otps", "otps",
       "user_id purpose code_hash status attempts:i max_attempts:i created_at:d expires_at:d"),
    _t(CORE, "RefreshSessions", "refresh_sessions",
       "jti user_id created_at:d expires_at:d revoked_at:d",
       unique=[["jti"]]),
    _t(CORE, "Settings", "system_settings",
       "key value updated_by created_at:d updated_at:d",
       unique=[["key"]]),
    _t(CORE, "AuditLogs", "audit_logs",
       "action actor_user_id target_user_id before:j after:j reason metadata:j request_id timestamp:d",
       ordered_by="timestamp"),
    _t(CORE, "ApiKeys", "api_keys",
       "key_id name key_hash prefix scope created_by created_at:d last_used_at:d revoked_at:d",
       unique=[["key_hash"], ["key_id"]]),
    _t(CORE, "Webhooks", "webhooks",
       "webhook_id name url secret events:j enabled:b created_by created_at:d",
       unique=[["webhook_id"]]),
    _t(CORE, "BlockedIps", "blocked_ips",
       "ip_address block_reason campaign_id publisher_id manager_id first_detected_at:d last_detected_at:d detection_count:i status under_investigation:b detection_source created_by updated_by created_at:d updated_at:d",
       unique=[["ip_address"]]),
    _t(CORE, "PurgeOperations", "purge_operations",
       "purge_id campaign_id campaign_name status actor_user_id request_id planned_counts:j deleted_counts:j verification:j error created_at:d updated_at:d completed_at:d",
       unique=[["purge_id"]]),
    # ---------------------------------------------------------- TRACKING ----
    _t(TRACKING, "TrackingLinks", "tracking_links",
       "link_id public_code campaign_id campaign_code publisher_id publisher_code manager_id status created_by created_at:d updated_at:d",
       unique=[["link_id"], ["public_code"]]),
    _t(TRACKING, "Clicks", "clicks",
       "digisnr_click_id campaign_id campaign_code publisher_id publisher_code manager_id link_id link_code original_params:j ip user_agent country state city source_click_id external_click_id agency_click_id config_version:i click_created_at:d "
       "sub_id_1 sub_id_2 sub_id_3 sub_id_4 sub_id_5 sub_id_6 sub_id_7 sub_id_8 sub_id_9 sub_id_10 utm_source utm_medium utm_campaign utm_term utm_content",
       unique=[["digisnr_click_id"]], ordered_by="click_created_at"),
    _t(TRACKING, "Conversions", "conversions",
       "conversion_id idempotency_key platform campaign_id campaign_code publisher_id publisher_code manager_id link_id digisnr_click_id external_click_id agency_click_id sub_affiliate_id external_conversion_id "
       "event goal raw_event_value raw_goal_value status raw_status advertiser_revenue:f upstream_payout:f sale_amount:f currency payout:f payout_note approval_status suspicious_velocity:b sub_ids:j utm:j "
       "click_created_at:d event_occurred_at:d postback_received_at:d conversion_created_at:d config_version:i request_id "
       "approval_decided_by approval_decided_at:d approval_note updated_at:d",
       unique=[["conversion_id"], ["idempotency_key"]], ordered_by="conversion_created_at"),
    _t(TRACKING, "InboundPostbacks", "inbound_postbacks",
       "postback_id platform campaign_id endpoint_id conversion_id result status http_status:i error payload:j received_at:d",
       unique=[["postback_id"]], ordered_by="received_at"),
    _t(TRACKING, "PostbackEndpoints", "postback_endpoints",
       "endpoint_id token campaign_id platform status received_count:i failure_count:i last_received_at:d created_by created_at:d updated_at:d",
       unique=[["token"], ["endpoint_id"]]),
    # Publisher postback configuration (versioned; campaign_id empty = Global).
    _t(TRACKING, "PublisherPostbackConfigs", "publisher_postback_configs",
       "publisher_id campaign_id version:i url_template macros_selected:j enabled:b deleted:b created_by created_at:d"),
    # Delivery log of publisher postbacks (a.k.a. Postback Logs).
    _t(TRACKING, "OutboundPostbacks", "outbound_postbacks",
       "outbound_id conversion_id publisher_id campaign_id event status url macros_used:j config_version:i config_scope attempts:j attempt_count:i final_status refired_by refired_at:d created_at:d",
       unique=[["outbound_id"]], ordered_by="created_at"),
    _t(TRACKING, "WebhookDeliveries", "webhook_deliveries",
       "delivery_id webhook_id event status http_status:i attempts:i error payload:j created_at:d",
       unique=[["delivery_id"]]),
    _t(TRACKING, "ExportJobs", "export_jobs",
       "job_id publisher_id kind format filters:j status records:i truncated:b error content created_at:d completed_at:d",
       unique=[["job_id"]]),
    _t(TRACKING, "SupportTickets", "support_tickets",
       "ticket_id subject category priority created_by_user_id created_by_role publisher_id manager_id status messages:j created_at:d updated_at:d resolved_at:d closed_at:d",
       unique=[["ticket_id"]]),
    # Legacy overflow table (not created in Postgres, which has no per-value size limit).
    _t(TRACKING, "Blobs", "_blobs", "blob_id seq:i data created_at:d", unique=[["blob_id", "seq"]]),
    # ----------------------------------------------------------- FINANCE ----
    # Postgres tables (migrations 001/002). Wallet balance, payments and payout
    # adjustments are NOT separate tables in the application: the wallet is a
    # live projection of FinancialLedger, a payment is a Withdrawal reaching
    # status 'paid', and a payout adjustment is a ledger row of type
    # adjustment_credit / adjustment_debit. They are preserved as such.
    _t(FINANCE, "FinancialLedger", "financial_ledger",
       "ledger_id idempotency_key transaction_type direction publisher_id manager_id campaign_id conversion_id withdrawal_id amount:m currency status source reference actor_user_id request_id metadata:j created_at:d effective_at:d",
       unique=[["ledger_id"], ["idempotency_key"]], ordered_by="created_at", append_only=True,
       autoinc="id", id_field="ledger_id"),
    _t(FINANCE, "Withdrawals", "withdrawals",
       "withdrawal_id idempotency_key publisher_id manager_id amount:m currency status reference rejection_reason requested_at:d updated_at:d reviewed_by paid_by",
       unique=[["withdrawal_id"], ["idempotency_key"]], ordered_by="requested_at", autoinc="id", id_field="withdrawal_id"),
]

BY_TAB = {t["tab"]: t for t in TABLES}
BY_COLLECTION = {t["collection"]: t for t in TABLES}
