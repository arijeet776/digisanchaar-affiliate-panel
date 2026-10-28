from fastapi import APIRouter

from app.api.v1.endpoints import (
    announcements,
    admin_dashboard,
    admin_financials,
    campaign_access,
    click_reports,
    conversion_review,
    admin_security,
    admin_managers,
    audit_logs,
    auth,
    campaigns,
    fraud,
    health,
    integrations,
    invites,
    links,
    manager,
    onboarding,
    otp,
    postbacks,
    publisher,
    publishers,
    purge,
    reports,
    settings,
    wallet,
    support,
)
from app.api.v1.endpoints import click as click_endpoint

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(otp.router, prefix="/otp", tags=["otp"])
api_router.include_router(invites.router, prefix="/invites", tags=["invites"])
api_router.include_router(onboarding.router, prefix="/onboarding", tags=["onboarding"])
api_router.include_router(admin_managers.router, prefix="/admin/managers", tags=["admin:managers"])
api_router.include_router(publishers.router, prefix="/publishers", tags=["publishers"])
# --- Part 3 ---
api_router.include_router(admin_dashboard.router, prefix="/admin/dashboard", tags=["admin:dashboard"])
api_router.include_router(campaigns.router, prefix="/admin/campaigns", tags=["admin:campaigns"])
api_router.include_router(audit_logs.router, prefix="/admin/audit-logs", tags=["admin:audit-logs"])
api_router.include_router(fraud.router, prefix="/admin/fraud", tags=["admin:fraud"])
# --- Part 4 foundation (purge + tracking-domain config) ---
api_router.include_router(purge.router, prefix="/admin/campaigns", tags=["admin:campaigns:purge"])
api_router.include_router(settings.router, prefix="/admin/settings", tags=["admin:settings"])
# --- Part 16.2 (global accent theme: public read, Super Admin write above) ---
api_router.include_router(settings.public_router, prefix="/appearance", tags=["appearance"])
# --- Part 4 (Manager panel) ---
api_router.include_router(manager.router, prefix="/manager", tags=["manager"])
# --- Part 5 (tracking engine) ---
api_router.include_router(links.router, prefix="/links", tags=["tracking:links"])
api_router.include_router(click_endpoint.router, prefix="/t", tags=["tracking:click"], include_in_schema=False)
# --- Part 6 (conversions + postbacks) ---
api_router.include_router(postbacks.router, prefix="/admin/postback", tags=["admin:postback"])
api_router.include_router(postbacks.public_router, prefix="/postback", tags=["postback:inbound"], include_in_schema=False)
# --- Part 7 (publisher panel) ---
api_router.include_router(publisher.router, prefix="/publisher", tags=["publisher"])
# --- Part 8 (reporting) ---
api_router.include_router(reports.router, prefix="/admin/reports", tags=["admin:reports"])
api_router.include_router(click_reports.router, prefix="/click-reports", tags=["click-reports"])
# --- Part 10 (integrations / machine API / webhooks) ---
api_router.include_router(integrations.router, prefix="/admin/integrations", tags=["admin:integrations"])
api_router.include_router(integrations.machine_router, prefix="/api", tags=["machine-api"], include_in_schema=False)
# --- Part 9 (financials + payments) ---
api_router.include_router(wallet.router, prefix="/wallet", tags=["wallet"])
api_router.include_router(admin_financials.router, prefix="/admin/financials", tags=["admin:financials"])

api_router.include_router(campaign_access.router, prefix="/campaign-access", tags=["campaign-access"])
api_router.include_router(conversion_review.router, prefix="/admin/conversion-review", tags=["admin:conversion-review"])

# --- Part 11 (security / operations / support) ---
api_router.include_router(support.router, prefix="/support", tags=["support"])
api_router.include_router(admin_security.router, prefix="/admin/security", tags=["admin:security"])

# --- Notifications: Super Admin broadcast messages ---
api_router.include_router(announcements.router, prefix="/announcements", tags=["announcements"])
