import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../components/AppShell";
import { ErrorBanner, StatusBadge } from "../../components/Common";

interface ManagerCampaignDetail {
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
  description: string | null;
  instructions: string | null;
  postback_platform: string | null;
  created_at: string;
}

export function ManagerCampaignDetailPage() {
  const { campaignId } = useParams<{ campaignId: string }>();
  const [campaign, setCampaign] = useState<ManagerCampaignDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ManagerCampaignDetail>(`/manager/campaigns/${campaignId}`)
      .then((r) => setCampaign(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load campaign"));
  }, [campaignId]);

  return (
    <AppShell title="Campaign">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-subtitle">
            <Link to="/manager/campaigns">Campaigns</Link> / {campaign?.name ?? "…"}
          </div>
          <div className="qx-page-title" data-testid="manager-campaign-title">{campaign?.name ?? "Campaign"}</div>
        </div>
        {campaign && <StatusBadge status={campaign.status} />}
      </div>

      <ErrorBanner message={error} />

      {campaign && (
        <>
          <div className="qx-row" style={{ marginBottom: 18 }}>
            <div className="qx-card">
              <div className="qx-kpi-label">Campaign ID</div>
              <div data-testid="manager-campaign-id">{campaign.campaign_id}</div>
            </div>
            <div className="qx-card">
              <div className="qx-kpi-label">Advertiser</div>
              <div>{campaign.advertiser_name ?? "—"}</div>
            </div>
            <div className="qx-card">
              <div className="qx-kpi-label">Postback Platform</div>
              <div style={{ textTransform: "capitalize" }}>{campaign.postback_platform ?? "—"}</div>
            </div>
            <div className="qx-card">
              <div className="qx-kpi-label">Caps</div>
              <div>
                Daily: {campaign.daily_cap ?? "Unlimited"} · Overall: {campaign.overall_cap ?? "Unlimited"}
              </div>
            </div>
          </div>

          <div className="qx-section-title">Events &amp; payouts</div>
          <div className="qx-table-wrap" data-testid="manager-campaign-events" style={{ marginBottom: 18 }}>
            <table className="qx-table">
              <thead>
                <tr><th>Event</th><th>Payout</th><th>Source</th></tr>
              </thead>
              <tbody>
                {campaign.events.map((e, i) => (
                  <tr key={i}>
                    <td>{e.event_name}</td>
                    <td className="qx-amount positive">₹{e.payout.toLocaleString("en-IN")}</td>
                    <td style={{ textTransform: "capitalize" }}>{e.completion_source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {campaign.description && (
            <>
              <div className="qx-section-title">Description</div>
              <div className="qx-card" style={{ marginBottom: 14, fontSize: 13, color: "var(--text-secondary)" }}>{campaign.description}</div>
            </>
          )}
          {campaign.instructions && (
            <>
              <div className="qx-section-title">Instructions</div>
              <div className="qx-card" style={{ fontSize: 13, color: "var(--text-secondary)" }}>{campaign.instructions}</div>
            </>
          )}
        </>
      )}
    </AppShell>
  );
}
