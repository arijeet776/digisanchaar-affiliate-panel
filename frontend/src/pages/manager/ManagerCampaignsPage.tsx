import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../components/AppShell";
import { ErrorBanner, StatusBadge } from "../../components/Common";

interface ManagerCampaign {
  campaign_id: string;
  name: string;
  status: string;
  advertiser_name: string | null;
  platform: string | null;
  payout_min: number | null;
  payout_max: number | null;
  events: { event_name: string; payout: number; completion_source: string }[];
  daily_cap: number | null;
  overall_cap: number | null;
}

const inr = (v: number | null) => (v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN")}`);

export function ManagerCampaignsPage() {
  const [campaigns, setCampaigns] = useState<ManagerCampaign[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ManagerCampaign[]>("/manager/campaigns")
      .then((r) => setCampaigns(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load campaigns"));
  }, []);

  return (
    <AppShell title="Campaigns">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Campaigns</div>
          <div className="qx-page-subtitle">Active network campaigns available to your publishers.</div>
        </div>
      </div>

      <ErrorBanner message={error} />

      {!campaigns ? (
        <div className="qx-empty-state">Loading…</div>
      ) : campaigns.length === 0 ? (
        <div className="qx-empty-state" data-testid="manager-campaigns-empty">No active campaigns right now.</div>
      ) : (
        <div className="qx-table-wrap" data-testid="manager-campaigns-table">
          <table className="qx-table">
            <thead>
              <tr>
                <th>Campaign</th>
                <th>Advertiser</th>
                <th>Platform</th>
                <th>Events</th>
                <th>Payout Range</th>
                <th>Daily Cap</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => (
                <tr key={c.campaign_id}>
                  <td>
                    <Link to={`/manager/campaigns/${c.campaign_id}`} data-testid={`manager-campaign-${c.campaign_id}`}>
                      {c.name}
                    </Link>
                  </td>
                  <td>{c.advertiser_name ?? "—"}</td>
                  <td>{c.platform ?? "—"}</td>
                  <td>{c.events.length}</td>
                  <td>
                    {inr(c.payout_min)} – {inr(c.payout_max)}
                  </td>
                  <td>{c.daily_cap ?? "Unlimited"}</td>
                  <td><StatusBadge status={c.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AppShell>
  );
}
