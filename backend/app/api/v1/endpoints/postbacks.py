"""Postback endpoints (Part 6).

Admin (Super Admin only): endpoint management, platform metadata, logs, refire.
Publisher: own outbound postback configuration (versioned).
Public: /postback/inbound/{platform}/{token} — no session auth; the token in
the path IS the credential (spec §21), rate-limited, and every request is
logged whether it processes or not.
"""
from fastapi import APIRouter, Depends, Query, Request

from app.core.enums import Role
from app.core.exceptions import NotFoundError
from app.core.logging_config import request_id_ctx
from app.core.rate_limit_dependency import rate_limit
from app.core.rbac import CurrentUser, require_role
from app.db import conversion_repository, publisher_repository
from app.schemas.postbacks import (
    InboundLogItem,
    OutboundLogItem,
    PostbackEndpointCreateRequest,
    PostbackEndpointCreatedResponse,
    GlobalPostbackRequest,
    PostbackEndpointSafeResponse,
    PublisherPostbackConfigRequest,
)
from app.services import conversion_service, postback_adapters, postback_service
from app.services.macro_engine import PUBLISHER_MACROS

router = APIRouter()
public_router = APIRouter()

_super_admin_only = require_role(Role.SUPER_ADMIN)
_publisher_only = require_role(Role.PUBLISHER)


# ---------- Super Admin: Postback Setup (spec §14/§21) ----------

@router.get("/platforms")
async def platforms(user: CurrentUser = Depends(_super_admin_only)):
    return postback_adapters.PLATFORM_METADATA


@router.post("/endpoints", response_model=PostbackEndpointCreatedResponse)
async def create_endpoint(body: PostbackEndpointCreateRequest, request: Request, user: CurrentUser = Depends(_super_admin_only)):
    doc = await postback_service.create_endpoint(body.campaign_id, body.platform, user.user_id)
    mapping = await postback_service.campaign_mapping(body.campaign_id)
    return postback_service.serialize_endpoint(doc, str(request.base_url), mapping)


@router.get("/endpoints", response_model=list[PostbackEndpointSafeResponse])
async def list_endpoints(campaign_id: str | None = None, user: CurrentUser = Depends(_super_admin_only)):
    docs = await conversion_repository.list_endpoints(campaign_id)
    return [postback_service.serialize_endpoint_safe(d) for d in docs]


@router.post("/endpoints/{endpoint_id}/disable", response_model=PostbackEndpointSafeResponse)
async def disable_endpoint(endpoint_id: str, user: CurrentUser = Depends(_super_admin_only)):
    doc = await postback_service.set_endpoint_status(endpoint_id, "disabled", user.user_id)
    return postback_service.serialize_endpoint_safe(doc)


@router.post("/endpoints/{endpoint_id}/enable", response_model=PostbackEndpointSafeResponse)
async def enable_endpoint(endpoint_id: str, user: CurrentUser = Depends(_super_admin_only)):
    doc = await postback_service.set_endpoint_status(endpoint_id, "active", user.user_id)
    return postback_service.serialize_endpoint_safe(doc)


@router.get("/logs", response_model=list[InboundLogItem])
async def inbound_logs(
    platform: str | None = None,
    campaign_id: str | None = None,
    processing_status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(_super_admin_only),
):
    items, _total = await conversion_repository.list_inbound(
        platform=platform, campaign_id=campaign_id, processing_status=processing_status,
        skip=(page - 1) * page_size, limit=page_size,
    )
    return [
        InboundLogItem(
            postback_id=i["postback_id"], platform=i["platform"], campaign_id=i["campaign_id"],
            received_at=i["received_at"], processing_status=i["processing_status"],
            event=i.get("event"), status=i.get("status"),
            digisnr_click_id=i.get("digisnr_click_id"), external_click_id=i.get("external_click_id"),
            external_conversion_id=i.get("external_conversion_id"),
            conversion_id=i.get("conversion_id"), error=i.get("error"),
        )
        for i in items
    ]


def _outbound_item(o: dict) -> OutboundLogItem:
    """Log projection: URL is masked for display (secret-looking params); the
    stored URL used for re-fire is untouched. Attempts expose status/error/time
    only - never response bodies."""
    attempts = [
        {"attempt": a.get("attempt"), "http_status": a.get("http_status"), "error": a.get("error"),
         "sent_at": a.get("sent_at"), "latency_ms": a.get("latency_ms"), "manual": bool(a.get("manual"))}
        for a in (o.get("attempts") or [])
    ]
    last = attempts[-1] if attempts else {}
    return OutboundLogItem(
        outbound_id=o["outbound_id"], conversion_id=o["conversion_id"],
        publisher_id=o["publisher_id"], campaign_id=o["campaign_id"],
        event=o.get("event"), url=postback_service.safe_url(o["url"]), attempt_count=o.get("attempt_count", 0),
        final_status=o["final_status"], created_at=o["created_at"],
        http_status=last.get("http_status"), last_error=last.get("error"),
        attempts=attempts, config_scope=o.get("config_scope"),
    )


@router.get("/outbound", response_model=list[OutboundLogItem])
async def outbound_logs(
    publisher_id: str | None = None,
    campaign_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(_super_admin_only),
):
    items, _total = await conversion_repository.list_outbound(
        publisher_id=publisher_id, campaign_id=campaign_id, skip=(page - 1) * page_size, limit=page_size,
    )
    return [
        _outbound_item(o) for o in items
    ]


@router.post("/outbound/{outbound_id}/refire", response_model=OutboundLogItem)
async def refire_outbound(outbound_id: str, user: CurrentUser = Depends(_super_admin_only)):
    updated = await postback_service.refire_outbound(outbound_id, user.user_id)
    return _outbound_item(updated)


# ---------- Publisher: own outbound postback config (spec §20) ----------

@router.put("/publisher-config")
async def save_publisher_config(body: PublisherPostbackConfigRequest, user: CurrentUser = Depends(_publisher_only)):
    profile = await publisher_repository.get_publisher_by_user_id(user.user_id)
    if profile is None:
        raise NotFoundError("Publisher profile not found")
    doc = await postback_service.save_publisher_config(profile["publisher_id"], body.campaign_id, body.url, user.user_id, enabled=body.enabled)
    return {"version": doc["version"], "enabled": doc["enabled"], "campaign_id": doc["campaign_id"]}


@router.post("/publisher-config/test")
async def test_publisher_config(body: PublisherPostbackConfigRequest, user: CurrentUser = Depends(_publisher_only)):
    profile = await publisher_repository.get_publisher_by_user_id(user.user_id)
    if profile is None:
        raise NotFoundError("Publisher profile not found")
    return await postback_service.send_test_postback(profile["publisher_id"], body.campaign_id, body.url)


@router.get("/publisher-config")
async def get_publisher_config(campaign_id: str | None = None, user: CurrentUser = Depends(_publisher_only)):
    profile = await publisher_repository.get_publisher_by_user_id(user.user_id)
    if profile is None:
        raise NotFoundError("Publisher profile not found")
    doc = await conversion_repository.get_postback_config(profile["publisher_id"], campaign_id)
    if doc is None:
        return {"configured": False}
    return {
        "configured": True,
        "url_template": doc["url_template"],
        "version": doc["version"],
        "campaign_id": doc["campaign_id"],
        "enabled": doc["enabled"],
    }


# ---------- Publisher: Global Postback (campaign_id = null) + macro vocabulary ----------

@router.get("/macros")
async def publisher_macros(user: CurrentUser = Depends(_publisher_only)):
    """The publisher-facing macro vocabulary (single source of truth for UI + validation)."""
    return PUBLISHER_MACROS


async def _publisher_profile(user: CurrentUser) -> dict:
    profile = await publisher_repository.get_publisher_by_user_id(user.user_id)
    if profile is None:
        raise NotFoundError("Publisher profile not found")
    return profile


def _global_view(doc: dict | None) -> dict:
    if doc is None or doc.get("deleted"):
        return {"configured": False, "enabled": False, "url_template": "", "macros_selected": [],
                "version": doc["version"] if doc else None, "updated_at": doc.get("created_at") if doc else None}
    return {"configured": True, "enabled": bool(doc.get("enabled")), "url_template": doc["url_template"],
            "macros_selected": doc.get("macros_selected") or [], "version": doc["version"],
            "updated_at": doc.get("created_at")}


@router.get("/global-config")
async def get_global_config(user: CurrentUser = Depends(_publisher_only)):
    profile = await _publisher_profile(user)
    return _global_view(await conversion_repository.get_latest_global_config(profile["publisher_id"]))


@router.put("/global-config")
async def save_global_config(body: GlobalPostbackRequest, user: CurrentUser = Depends(_publisher_only)):
    profile = await _publisher_profile(user)
    doc = await postback_service.save_publisher_config(profile["publisher_id"], None, body.url, user.user_id, enabled=body.enabled)
    return _global_view(doc)


@router.delete("/global-config")
async def delete_global_config(user: CurrentUser = Depends(_publisher_only)):
    profile = await _publisher_profile(user)
    removed = await postback_service.delete_global_config(profile["publisher_id"], user.user_id)
    return {"deleted": removed}


# ---------- Public inbound receiver ----------

@public_router.api_route(
    "/inbound/{platform}/{token}",
    methods=["GET", "POST"],
    dependencies=[Depends(rate_limit("postback_inbound", limit=120, window_seconds=60))],
    include_in_schema=False,
)
async def receive_inbound(platform: str, token: str, request: Request):
    params: dict = dict(request.query_params)
    if request.method == "POST":
        content_type = request.headers.get("content-type", "")
        try:
            if "application/json" in content_type:
                body = await request.json()
                if isinstance(body, dict):
                    params.update({k: v for k, v in body.items()})
            elif "form" in content_type:
                params.update(dict(await request.form()))
        except Exception:  # noqa: BLE001 — malformed body → params as-is; adapter validation decides
            pass
    result = await conversion_service.process_inbound(platform, token, params, request_id_ctx.get())
    from fastapi.responses import JSONResponse

    return JSONResponse(result["body"], status_code=result["http_status"])
