"""
Tracking-domain configuration — Final Execution Directive §19, master
spec §15-19 / §25-31.

The active tracking base URL is RUNTIME configuration stored in the
database (system_settings collection), changeable only by an authorized
Super Admin from System Settings → Domain & Tracking. TRACKING_BASE_URL in
the environment is a bootstrap default only — when a DB value exists it
wins (spec §29: the backend is the authoritative resolver).

Nothing in this module — or anywhere else — may hard-code a production
tracking/panel domain (spec §15; §30 audit requirement).
"""
import logging
from urllib.parse import urlsplit

from app.config import get_settings
from app.core import audit_actions
from app.core.exceptions import ValidationAppError
from app.db import settings_repository
from app.db.audit_repository import record as audit_record

logger = logging.getLogger(__name__)

VERIFICATION_NOTE = "URL format valid — domain ownership verification not implemented."


def validate_tracking_base_url(raw: str | None, *, is_production: bool) -> str:
    """Spec §19 validation. Returns the normalized URL or raises ValidationAppError."""
    if raw is None:
        raise ValidationAppError("tracking_base_url is required")
    candidate = raw.strip()
    if not candidate:
        raise ValidationAppError("tracking_base_url must not be empty")
    if candidate != raw or any(ch.isspace() for ch in candidate):
        raise ValidationAppError("tracking_base_url must not contain whitespace")

    try:
        parts = urlsplit(candidate)
        port = parts.port  # property access validates the port (raises on garbage)
    except ValueError as exc:
        raise ValidationAppError("tracking_base_url is not a valid absolute URL") from exc

    scheme = parts.scheme.lower()
    allowed_schemes = {"https"} if is_production else {"https", "http"}
    if scheme not in allowed_schemes:
        # An allowlist (not a denylist) is what rejects javascript:/data:/file:
        # and every future scheme we haven't thought of.
        raise ValidationAppError(
            "Unsupported URL scheme — production requires HTTPS"
            if is_production
            else "Unsupported URL scheme — only http/https are allowed"
        )
    if not parts.hostname:
        raise ValidationAppError("tracking_base_url must include a host")
    if parts.username is not None or parts.password is not None:
        raise ValidationAppError("tracking_base_url must not contain credentials")
    if parts.query:
        raise ValidationAppError("tracking_base_url must not contain a query string")
    if parts.fragment:
        raise ValidationAppError("tracking_base_url must not contain a fragment")

    host = parts.hostname.lower()
    netloc = f"{host}:{port}" if port else host
    path = parts.path.rstrip("/")  # normalized trailing slash (spec §19)
    return f"{scheme}://{netloc}{path}"


def build_tracking_url_from_base(base_url: str, campaign_code: str, link_code: str) -> str:
    """Canonical short public tracking URL (spec §20/§25): {base}/{campaign-code}/{link-code}."""
    return f"{base_url.rstrip('/')}/{campaign_code}/{link_code}"


def _serialize(doc: dict | None, effective_source: str | None, effective_value: str | None) -> dict:
    base_url = doc["value"] if doc else effective_value
    configured = base_url is not None
    return {
        "configured": configured,
        "tracking_base_url": base_url,
        "status": "format_valid" if configured else "not_configured",
        "verified": False,
        "verified_at": None,
        "verification_note": VERIFICATION_NOTE if configured else "No tracking domain configured yet.",
        "effective_source": effective_source,
        "example_url": build_tracking_url_from_base(base_url, "C7K29", "X8Q2") if base_url else None,
        "created_at": doc["created_at"] if doc else None,
        "updated_at": doc["updated_at"] if doc else None,
        "updated_by": doc["updated_by"] if doc else None,
    }


async def get_tracking_domain_config() -> dict:
    doc = await settings_repository.get_setting(settings_repository.TRACKING_DOMAIN_KEY)
    if doc:
        return _serialize(doc, "database", doc["value"])
    env_default = get_settings().tracking_base_url
    if env_default:
        return _serialize(None, "environment", env_default)
    return _serialize(None, None, None)


async def update_tracking_domain(raw_url: str, actor_user_id: str, reason: str | None = None) -> dict:
    settings = get_settings()
    normalized = validate_tracking_base_url(raw_url, is_production=settings.is_production)

    # Tracking links are served by the BACKEND (click route at the app root). If the frontend
    # host (a CORS origin, e.g. the Netlify site) is used, every link returns 404.
    frontend_hosts = {urlsplit(o).hostname for o in settings.allowed_origins_list if o and o != "*"}
    if urlsplit(normalized).hostname in frontend_hosts:
        raise ValidationAppError(
            "Tracking domain must be the BACKEND (API) URL, not the frontend site. "
            "Use the Render service URL, e.g. https://<your-service>.onrender.com"
        )

    existing = await settings_repository.get_setting(settings_repository.TRACKING_DOMAIN_KEY)
    old_value = existing["value"] if existing else None

    doc = await settings_repository.upsert_setting(
        settings_repository.TRACKING_DOMAIN_KEY, normalized, actor_user_id
    )

    # Auditable configuration change (spec §26): old value, new value, actor,
    # reason, and the request id (stamped by audit_repository from the ctx).
    await audit_record(
        audit_actions.TRACKING_DOMAIN_UPDATED,
        actor_user_id=actor_user_id,
        target_user_id=None,
        before={"tracking_base_url": old_value},
        after={"tracking_base_url": normalized},
        reason=reason,
        metadata={
            "note": "Applies to newly generated links only; historical click/conversion/"
                    "attribution/earning records are never rewritten (spec §25)."
        },
    )
    return _serialize(doc, "database", normalized)


async def get_active_tracking_base_url() -> str | None:
    """Authoritative resolver (spec §29): DB value wins; env is the bootstrap default."""
    doc = await settings_repository.get_setting(settings_repository.TRACKING_DOMAIN_KEY)
    if doc:
        return doc["value"]
    return get_settings().tracking_base_url


async def build_tracking_url(campaign_code: str, link_code: str) -> str | None:
    """Used by the Part 5 tracking engine; returns None (not an invented
    domain) when no tracking domain is configured."""
    base = await get_active_tracking_base_url()
    if base is None:
        return None
    return build_tracking_url_from_base(base, campaign_code, link_code)


# --- Global accent theme (Part 16.2) -----------------------------------------
# Presentation-only configuration. Stored in the same system_settings
# collection under key "accent_theme". Missing/invalid stored values fall back
# to the default so a bad document can never break the UI or startup.
ACCENT_THEMES = ("deep-yellow", "deep-sky", "deep-orange", "hasmind-purple")
DEFAULT_ACCENT_THEME = "deep-yellow"


async def get_accent_theme() -> dict:
    try:
        doc = await settings_repository.get_setting(settings_repository.ACCENT_THEME_KEY)
    except Exception:  # noqa: BLE001 - appearance must never take the app down
        logger.warning("accent theme lookup failed; using default", exc_info=True)
        doc = None
    if doc and doc.get("value") in ACCENT_THEMES:
        return {"accent_theme": doc["value"], "is_default": False, "updated_at": doc.get("updated_at")}
    return {"accent_theme": DEFAULT_ACCENT_THEME, "is_default": True, "updated_at": None}


async def update_accent_theme(theme: str, actor_user_id: str) -> dict:
    if theme not in ACCENT_THEMES:
        raise ValidationAppError(f"accent_theme must be one of: {', '.join(ACCENT_THEMES)}")
    before = (await get_accent_theme())["accent_theme"]
    doc = await settings_repository.upsert_setting(settings_repository.ACCENT_THEME_KEY, theme, actor_user_id)
    await audit_record(
        audit_actions.ACCENT_THEME_UPDATED,
        actor_user_id=actor_user_id,
        target_user_id=None,
        before={"accent_theme": before},
        after={"accent_theme": theme},
        reason=None,
        metadata={"note": "Global presentation accent; does not affect business data."},
    )
    return {"accent_theme": theme, "is_default": False, "updated_at": doc["updated_at"]}


# ---- Support / Community: DigiSanchaar WhatsApp Group link (Part 17) ----------
_WHATSAPP_HOSTS = ("chat.whatsapp.com", "wa.me", "whatsapp.com")


def validate_whatsapp_link(raw: str | None) -> str:
    """Empty string clears the setting. Otherwise must be an https WhatsApp
    URL - never an arbitrary link a Publisher could be redirected to."""
    from urllib.parse import urlsplit

    value = (raw or "").strip()
    if not value:
        return ""
    if len(value) > 300:
        raise ValidationAppError("WhatsApp link is too long")
    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise ValidationAppError("WhatsApp link is not a valid URL") from exc
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() != "https" or parts.username or parts.password:
        raise ValidationAppError("WhatsApp link must be a plain https URL")
    if not any(host == h or host.endswith("." + h) for h in _WHATSAPP_HOSTS):
        raise ValidationAppError("Enter a WhatsApp group link (chat.whatsapp.com/...)")
    return value


async def get_whatsapp_group_link() -> dict:
    doc = await settings_repository.get_setting(settings_repository.WHATSAPP_GROUP_KEY)
    value = (doc or {}).get("value") or ""
    return {"whatsapp_group_link": value or None, "updated_at": (doc or {}).get("updated_at")}


async def update_whatsapp_group_link(raw: str | None, actor_user_id: str) -> dict:
    value = validate_whatsapp_link(raw)
    before = (await get_whatsapp_group_link())["whatsapp_group_link"]
    doc = await settings_repository.upsert_setting(settings_repository.WHATSAPP_GROUP_KEY, value, actor_user_id)
    await audit_record(
        audit_actions.WHATSAPP_GROUP_LINK_UPDATED, actor_user_id=actor_user_id, target_user_id=None,
        before={"configured": bool(before)}, after={"configured": bool(value)},
        metadata={"cleared": not value},
    )
    return {"whatsapp_group_link": value or None, "updated_at": doc["updated_at"]}
