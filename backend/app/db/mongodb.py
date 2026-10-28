"""
MongoDB (operational store) connection lifecycle.

Startup fix (Part 1 review): connect_to_mongo() no longer raises if Mongo is
unreachable at boot. It logs the failure and lets the app continue starting,
so /health/live still comes up. Motor's client is lazy anyway — creating it
does not require an active connection, and later calls will retry against
the driver's own topology monitor once Mongo becomes reachable. /health/ready
is what tells an orchestrator whether Mongo is actually usable right now.

Index creation is centralized here in `ensure_indexes()` so every module that
adds a collection also adds its indexes in one place instead of relying on
ad hoc index creation scattered across query code.
"""
import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings
from app.storage import runtime

logger = logging.getLogger(__name__)

# True once ensure_indexes() has completed without error for the current
# connection. If Mongo was down at startup, readiness retries index creation
# so unique indexes (e.g. users.email) are never silently missing.
_indexes_ready = False

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_to_mongo() -> None:
    """
    Best-effort at startup: always constructs the client (cheap, lazy), then
    tries a ping purely to log whether Mongo is reachable yet. Never raises —
    see module docstring for why fail-fast here would break /health/live.
    """
    global _client, _db
    settings = get_settings()
    if runtime.uses_adapter():
        # Supabase REST backend: no Mongo connection at all.
        if await runtime.get_adapter().ping():
            logger.info("Connected to the adapter-backed storage API (STORAGE_BACKEND=supabase_rest)")
        else:
            logger.warning("Storage API not reachable at startup - will keep retrying via /health/ready")
        return
    _client = AsyncIOMotorClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    _db = _client[settings.mongo_db_name]

    try:
        await _client.admin.command("ping")
        logger.info("Connected to MongoDB (%s)", settings.mongo_db_name)
        await ensure_indexes(_db)
    except Exception as exc:  # noqa: BLE001 — startup must not crash the process
        logger.warning(
            "MongoDB not reachable at startup (%s) — will keep retrying via /health/ready", exc
        )


async def close_mongo_connection() -> None:
    if runtime.uses_adapter():
        await runtime.close()
        return
    if _client is not None:
        _client.close()
        logger.info("MongoDB connection closed")


def get_database() -> AsyncIOMotorDatabase:
    if runtime.uses_adapter():
        return runtime.get_adapter_database()  # Motor-compatible facade over the Supabase adapter
    if _db is None:
        raise RuntimeError("MongoDB has not been initialized. Call connect_to_mongo() first.")
    return _db


async def ping_mongo() -> bool:
    if runtime.uses_adapter():
        return await runtime.get_adapter().ping()
    try:
        if _client is None:
            return False
        await _client.admin.command("ping")
        return True
    except Exception:  # noqa: BLE001 — health check must never raise
        return False


async def retry_indexes_if_needed() -> bool:
    """Called from /health/ready. No-op once indexes exist; otherwise retries
    index creation (idempotent). Returns whether indexes are in place."""
    if runtime.uses_adapter():
        return True  # uniqueness is enforced by the database schema
    if _indexes_ready:
        return True
    if _db is None:
        return False
    return await ensure_indexes(_db)


async def ensure_indexes(db: AsyncIOMotorDatabase) -> bool:
    """
    Indexes for every collection Part 1 + Part 2 actually use. Business
    collections from later parts (clicks, postback_logs, etc.) are added
    when those modules are built — adding them now against nonexistent
    collections would just be noise. Called both at startup (if Mongo is
    reachable) and safe to call again manually/on reconnect.
    """
    global _indexes_ready
    try:
        # Identity (Part 1 + Part 2)
        await db["users"].create_index("email", unique=True)

        # Business profiles (Part 2 §52) — unique on both the business id
        # and the identity FK, since each user has at most one profile.
        await db["managers"].create_index("manager_id", unique=True)
        await db["managers"].create_index("user_id", unique=True)
        await db["publishers"].create_index("publisher_id", unique=True)
        await db["publishers"].create_index("user_id", unique=True)
        await db["publishers"].create_index("manager_id")  # manager-scope queries (§34)

        # Invites (Part 2 §52) — token_hash is the primary lookup; status/
        # expires_at/role support admin listing and cleanup queries.
        await db["invites"].create_index("token_hash", unique=True)
        await db["invites"].create_index("status")
        await db["invites"].create_index("expires_at")
        await db["invites"].create_index("role")

        # OTPs (Part 2 §12-15, §53) — lookup by user+purpose+status is the
        # hot path (get_active_otp); TTL index auto-cleans expired codes
        # (spec §53 explicitly endorses TTL for OTPs, unlike invites/audit).
        await db["otps"].create_index([("user_id", 1), ("purpose", 1), ("status", 1)])
        await db["otps"].create_index("expires_at", expireAfterSeconds=0)

        # Refresh sessions (Part 2 §10-11) — jti is the lookup key on every
        # refresh/logout; TTL cleans up long-expired sessions automatically.
        await db["refresh_sessions"].create_index("jti", unique=True)
        await db["refresh_sessions"].create_index("user_id")
        await db["refresh_sessions"].create_index("expires_at", expireAfterSeconds=0)

        # Audit logs (Part 2 §44) — NOT TTL'd; these are a compliance/audit
        # trail, not disposable state (spec §53 explicitly warns against
        # TTL-deleting audit/financial records). Indexed for the queries an
        # admin/security review would actually run.
        await db["audit_logs"].create_index("target_user_id")
        await db["audit_logs"].create_index("actor_user_id")
        await db["audit_logs"].create_index("timestamp")
        await db["audit_logs"].create_index("action")

        # Campaigns (Part 3) — campaign_id is the business identifier (never
        # the Mongo _id); status/summary fields support admin-list filtering.
        # campaign_config_versions is append-only history: indexed by
        # (campaign_id, version) unique, since that pair is how any future
        # part resolves "which config applied at this point in time".
        await db["campaigns"].create_index("campaign_id", unique=True)
        await db["campaigns"].create_index("status")
        await db["campaigns"].create_index("summary.platform")
        await db["campaigns"].create_index("created_at")
        await db["campaign_config_versions"].create_index(
            [("campaign_id", 1), ("version", 1)], unique=True
        )
        await db["campaign_config_versions"].create_index("effective_from")

        # Blocked-IP registry (Part 3 fraud foundation) — ip_address is the
        # natural lookup key (create_or_bump reads/writes by it); status and
        # last_detected_at support the admin list view's filter/sort.
        await db["blocked_ips"].create_index("ip_address", unique=True)
        await db["blocked_ips"].create_index("status")
        await db["blocked_ips"].create_index("last_detected_at")

        # System settings (Part 4 foundation: tracking-domain config) — one
        # document per configuration key; ENV only provides bootstrap defaults.
        await db["system_settings"].create_index("key", unique=True)

        # Purge operations (campaign data purge) — one record per purge run;
        # campaign_id supports purge-history lookup and resumable operations.
        await db["purge_operations"].create_index("purge_id", unique=True)
        await db["purge_operations"].create_index("campaign_id")

        # Tracking (Part 5) — public codes are unique lookup keys; clicks are
        # append-only and keyed by the immutable DigiSNR click id.
        await db["tracking_links"].create_index("link_id", unique=True)
        await db["tracking_links"].create_index("public_code", unique=True)
        await db["tracking_links"].create_index([("campaign_id", 1), ("publisher_id", 1)])
        await db["tracking_links"].create_index("manager_id")
        await db["clicks"].create_index("digisnr_click_id", unique=True)
        await db["clicks"].create_index("campaign_id")
        await db["clicks"].create_index("publisher_id")
        await db["clicks"].create_index("link_id")
        await db["clicks"].create_index("click_created_at")

        # Conversions + postbacks (Part 6) — idempotency_key unique is the
        # hard guarantee against duplicate conversions (spec §23).
        await db["postback_endpoints"].create_index("token", unique=True)
        await db["postback_endpoints"].create_index("campaign_id")
        await db["conversions"].create_index("conversion_id", unique=True)
        await db["conversions"].create_index("idempotency_key", unique=True)
        await db["conversions"].create_index("campaign_id")
        await db["conversions"].create_index("publisher_id")
        await db["conversions"].create_index("digisnr_click_id")
        await db["inbound_postbacks"].create_index("postback_id", unique=True)
        await db["inbound_postbacks"].create_index([("platform", 1), ("received_at", -1)])
        await db["inbound_postbacks"].create_index("campaign_id")
        await db["outbound_postbacks"].create_index("outbound_id", unique=True)
        await db["outbound_postbacks"].create_index("conversion_id")
        await db["outbound_postbacks"].create_index("publisher_id")
        await db["publisher_postback_configs"].create_index([("publisher_id", 1), ("campaign_id", 1), ("version", -1)])

        # Integrations (Part 10) — API keys are stored as SHA-256 hashes only;
        # webhook deliveries are append-only logs.
        await db["api_keys"].create_index("key_hash", unique=True)
        await db["api_keys"].create_index("key_id", unique=True)
        await db["webhooks"].create_index("webhook_id", unique=True)
        await db["webhook_deliveries"].create_index("delivery_id", unique=True)
        await db["webhook_deliveries"].create_index("webhook_id")

        # Campaign access approvals
        await db["campaign_access"].create_index([("campaign_id", 1), ("publisher_id", 1)], unique=True)
        await db["campaign_access"].create_index("access_id", unique=True)
        await db["campaign_access"].create_index([("manager_id", 1), ("status", 1)])
        await db["conversions"].create_index([("approval_status", 1), ("manager_id", 1)])

        # Part 11 (Security / Operations / Support)
        await db["support_tickets"].create_index("ticket_id", unique=True)
        await db["support_tickets"].create_index("status")
        await db["support_tickets"].create_index("created_by_user_id")
        await db["support_tickets"].create_index("publisher_id")
        await db["support_tickets"].create_index("manager_id")
        await db["support_tickets"].create_index("updated_at")
        _indexes_ready = True
        return True
    except Exception as exc:  # noqa: BLE001 — index creation must not crash startup
        _indexes_ready = False
        logger.error("Could not ensure MongoDB indexes (will retry via /health/ready): %s", exc)
        return False
