"""Integration hub endpoints (Part 10): API key management, webhook management,
and the machine API itself (X-API-Key authenticated)."""
from fastapi import APIRouter, Depends, Query, Request

from app.core.enums import Role
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.core.rate_limit_dependency import rate_limit
from app.core.rbac import CurrentUser, require_role
from app.schemas.integrations import (
    ApiKeyCreateRequest,
    ApiKeyCreatedResponse,
    ApiKeyListItem,
    WebhookCreateRequest,
    WebhookCreatedResponse,
    WebhookDeliveryItem,
    WebhookListItem,
)
from app.services import apikey_service, reports_service, webhook_service

router = APIRouter()
machine_router = APIRouter()

_super_admin_only = require_role(Role.SUPER_ADMIN)


# ---------- API keys ----------

@router.post("/api-keys", response_model=ApiKeyCreatedResponse,
             dependencies=[Depends(rate_limit("apikey_create", limit=10, window_seconds=60))])
async def create_api_key(body: ApiKeyCreateRequest, user: CurrentUser = Depends(_super_admin_only)):
    return await apikey_service.create_api_key(body.name, body.scope, user.user_id)


@router.get("/api-keys", response_model=list[ApiKeyListItem])
async def list_api_keys(user: CurrentUser = Depends(_super_admin_only)):
    return await apikey_service.list_api_keys()


@router.post("/api-keys/{key_id}/revoke")
async def revoke_api_key(key_id: str, user: CurrentUser = Depends(_super_admin_only)):
    await apikey_service.revoke_api_key(key_id, user.user_id)
    return {"revoked": True, "key_id": key_id}


# ---------- Webhooks ----------

@router.post("/webhooks", response_model=WebhookCreatedResponse)
async def create_webhook(body: WebhookCreateRequest, user: CurrentUser = Depends(_super_admin_only)):
    doc = await webhook_service.create_webhook(body.name, body.url, body.events, user.user_id)
    return {**doc, "_id": None}


@router.get("/webhooks", response_model=list[WebhookListItem])
async def list_webhooks(user: CurrentUser = Depends(_super_admin_only)):
    return await webhook_service.list_webhooks()


@router.post("/webhooks/{webhook_id}/toggle", response_model=WebhookListItem)
async def toggle_webhook(webhook_id: str, user: CurrentUser = Depends(_super_admin_only)):
    current = await webhook_service.get_webhook(webhook_id)
    if current is None:
        raise NotFoundError("Webhook not found")
    return await webhook_service.set_webhook_enabled(webhook_id, not current["enabled"], user.user_id)


@router.post("/webhooks/{webhook_id}/disable", response_model=WebhookListItem)
async def disable_webhook(webhook_id: str, user: CurrentUser = Depends(_super_admin_only)):
    return await webhook_service.set_webhook_enabled(webhook_id, False, user.user_id)


@router.post("/webhooks/{webhook_id}/enable", response_model=WebhookListItem)
async def enable_webhook(webhook_id: str, user: CurrentUser = Depends(_super_admin_only)):
    return await webhook_service.set_webhook_enabled(webhook_id, True, user.user_id)


@router.get("/webhook-deliveries", response_model=list[WebhookDeliveryItem])
async def webhook_deliveries(webhook_id: str | None = None, user: CurrentUser = Depends(_super_admin_only)):
    return await webhook_service.list_deliveries(webhook_id)


@router.post("/webhook-deliveries/{delivery_id}/replay", response_model=WebhookDeliveryItem)
async def replay_delivery(delivery_id: str, user: CurrentUser = Depends(_super_admin_only)):
    return await webhook_service.replay_delivery(delivery_id, user.user_id)


# ---------- Machine API (X-API-Key auth — no sessions, no cookies) ----------

async def _require_api_key(request: Request, scope: str) -> dict:
    raw = request.headers.get("x-api-key")
    if not raw:
        raise UnauthorizedError("API key required (X-API-Key header)")
    return await apikey_service.verify_api_key(raw, scope)


@machine_router.get("/reports/summary",
                    dependencies=[Depends(rate_limit("machine_api", limit=60, window_seconds=60))])
async def machine_reports_summary(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    campaign_id: str | None = None,
    manager_id: str | None = None,
    publisher_id: str | None = None,
    event: str | None = None,
    group_by: str = Query(default="campaign", pattern="^(campaign|manager|publisher|event)$"),
):
    await _require_api_key(request, "reports:read")
    return await reports_service.build_report(
        date_from=date_from, date_to=date_to, campaign_id=campaign_id,
        manager_id=manager_id, publisher_id=publisher_id, event=event, group_by=group_by,
    )
