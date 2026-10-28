"""
Dashboard aggregation. Every number here comes from a real repository
query — Managers/Publishers/Campaigns counts all exist as real collections
by Part 3. Metrics that depend on data models from later parts (clicks,
conversions, revenue, payouts, margin — Parts 6/7/9) are represented
explicitly as `available: false` rather than as a fabricated 0 or "-",
which would be indistinguishable from a real zero. The frontend renders
these as a clearly marked foundation/empty state, not a metric card with a
number in it.
"""
import asyncio

from app.core.enums import AccountStatus, CampaignStatus, Role
from app.db import campaign_repository
from app.db.mongodb import get_database


class Metric:
    def __init__(self, available: bool, value: int | float | None = None, reason: str | None = None):
        self.available = available
        self.value = value
        self.reason = reason

    def to_dict(self):
        return {"available": self.available, "value": self.value, "reason": self.reason}


async def get_dashboard() -> dict:
    db = get_database()

    users = db["users"]
    mgr, pub = Role.MANAGER.value, Role.PUBLISHER.value
    act, pend = AccountStatus.ACTIVE.value, AccountStatus.PENDING.value
    # Eight independent reads: issued concurrently instead of one after another
    # (each is a storage round trip). Every number is still a real, fresh count.
    (total_managers, active_managers, total_publishers, active_publishers, pending_managers, pending_publishers,
     total_campaigns, active_campaigns) = await asyncio.gather(
        users.count_documents({"role": mgr}),
        users.count_documents({"role": mgr, "account_status": act}),
        users.count_documents({"role": pub}),
        users.count_documents({"role": pub, "account_status": act}),
        users.count_documents({"role": mgr, "account_status": pend}),
        users.count_documents({"role": pub, "account_status": pend}),
        campaign_repository.count_all_campaigns(),
        campaign_repository.count_campaigns_by_status(CampaignStatus.ACTIVE),
    )

    not_yet_available = "Requires a data model not yet built (Parts 6/7/9)"

    return {
        "kpis": {
            "total_managers": Metric(True, total_managers).to_dict(),
            "active_managers": Metric(True, active_managers).to_dict(),
            "total_publishers": Metric(True, total_publishers).to_dict(),
            "active_publishers": Metric(True, active_publishers).to_dict(),
            "active_campaigns": Metric(True, active_campaigns).to_dict(),
            "total_campaigns": Metric(True, total_campaigns).to_dict(),
            "total_clicks": Metric(False, reason=not_yet_available).to_dict(),
            "successful_events": Metric(False, reason=not_yet_available).to_dict(),
            "network_revenue": Metric(False, reason=not_yet_available).to_dict(),
            "publisher_payout": Metric(False, reason=not_yet_available).to_dict(),
            "network_margin": Metric(False, reason=not_yet_available).to_dict(),
        },
        "pending_approvals": {
            "managers": pending_managers,
            "publishers": pending_publishers,
        },
    }
