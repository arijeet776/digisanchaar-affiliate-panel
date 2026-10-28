import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ErrorBanner, LoadingState } from "../components/Common";
import { LineChart } from "../components/LineChart";
import { IconCampaign, IconFinancial, IconLink, IconReports } from "../components/Icons";

interface Totals { conversions: number; earnings: number; pending: number }
interface PublisherDashboard {
  publisher_id: string;
  public_code: string | null;
  display_name: string;
  clicks: number;
  conversions: number;
  earnings: number;
  links: number;
  stats: {
    month_label: string;
    month: Totals & { clicks: number };
    lifetime: Totals;
    daily: { day: string; label: string; conversions: number; earnings: number }[];
    top_campaigns: { campaign_id: string; name: string; clicks: number; conversions: number; earnings: number }[];
  };
  recent_conversions: {
    conversion_id: string; campaign_id: string; event: string | null; status: string | null;
    payout: number | null; conversion_created_at: string;
  }[];
}

const inr = (v: number) => `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;

function StatCard({ icon, label, value, hint }: { icon: ReactNode; label: string; value: string; hint?: ReactNode }) {
  return (
    <div className="qx-stat-card">
      <div className="qx-stat-watermark">{icon}</div>
      <div className="qx-stat-icon">{icon}</div>
      <div className="qx-stat-label">{label}</div>
      <div className="qx-stat-value">{value}</div>
      {hint && <div className="qx-stat-hint">{hint}</div>}
    </div>
  );
}

export function PublisherHomePage() {
  const [data, setData] = useState<PublisherDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<PublisherDashboard>("/publisher/dashboard")
      .then((r) => setData(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load dashboard"));
  }, []);

  const st = data?.stats;
  const cr = (conv: number, clicks: number) => (clicks > 0 ? ((conv / clicks) * 100).toFixed(2) : "0.00");

  return (
    <AppShell title="Dashboard Overview">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title qx-page-title-xl" data-testid="publisher-dashboard-title">Dashboard</div>
          <div className="qx-page-subtitle">
            Track your clicks, conversions, and operational insights.
            {data && <> <span data-testid="publisher-id" style={{ display: "none" }}>{data.publisher_id}</span></>}
          </div>
        </div>
      </div>

      <ErrorBanner message={error} />
      {!data && !error && <LoadingState variant="kpis" rows={8} />}

      {data && st && (
        <>
          <div className="qx-stat-grid qx-stat-grid-hiq">
            <StatCard icon={<IconLink width={22} height={22} />} label={`${st.month_label} Clicks`} value={st.month.clicks.toLocaleString("en-US")} />
            <StatCard icon={<IconReports width={22} height={22} />} label={`${st.month_label} Conversions`} value={st.month.conversions.toLocaleString("en-US")}
              hint={<><span className="qx-up">↗ {cr(st.month.conversions, st.month.clicks)}%</span> CR</>} />
            <StatCard icon={<IconFinancial width={22} height={22} />} label={`${st.month_label} Earnings`} value={inr(st.month.earnings)} />
            <StatCard icon={<IconFinancial width={22} height={22} />} label={`${st.month_label} Pending`} value={inr(st.month.pending)} />
            <StatCard icon={<IconLink width={22} height={22} />} label="Lifetime Clicks" value={data.clicks.toLocaleString("en-US")} />
            <StatCard icon={<IconReports width={22} height={22} />} label="Lifetime Conversions" value={st.lifetime.conversions.toLocaleString("en-US")}
              hint={<><span className="qx-up">↗ {cr(st.lifetime.conversions, data.clicks)}%</span> CR</>} />
            <StatCard icon={<IconFinancial width={22} height={22} />} label="Lifetime Earnings" value={inr(st.lifetime.earnings)} />
            <StatCard icon={<IconFinancial width={22} height={22} />} label="Lifetime Pending" value={inr(st.lifetime.pending)} />
          </div>

          <div className="qx-chart-grid">
            <div className="qx-card qx-chart-card">
              <div className="qx-chart-title"><span style={{ color: "var(--qx-success)" }}>∿</span> Conversions Trend <span className="qx-hint">({st.month_label})</span></div>
              <LineChart color="#10b981" points={st.daily.map((d) => ({ label: d.label, value: d.conversions }))} />
            </div>
            <div className="qx-card qx-chart-card">
              <div className="qx-chart-title"><IconReports width={16} height={16} style={{ color: "var(--qx-accent)" }} /> Earnings Overview <span className="qx-hint">({st.month_label})</span></div>
              <LineChart color="var(--accent-primary)" format={(v) => `${Math.round(v)}`} points={st.daily.map((d) => ({ label: d.label, value: d.earnings }))} />
            </div>
          </div>

          <div className="qx-card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "16px 18px" }}>
              <div className="qx-chart-title"><IconCampaign width={16} height={16} style={{ color: "var(--qx-accent)" }} /> Top Campaigns</div>
              <div className="qx-hint">Your best performing campaigns by volume.</div>
            </div>
            {st.top_campaigns.length === 0 ? (
              <div className="qx-empty-state">No traffic yet. Share your tracking links to get started.</div>
            ) : (
              <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch", touchAction: "pan-x pan-y" }}>
              <table className="qx-table" style={{ minWidth: 520 }} data-testid="publisher-recent-conversions">
                <thead><tr><th>Campaign</th><th style={{ textAlign: "right" }}>Clicks</th><th style={{ textAlign: "right" }}>Conv.</th><th style={{ textAlign: "right" }}>Earnings</th></tr></thead>
                <tbody>
                  {st.top_campaigns.map((c) => (
                    <tr key={c.campaign_id}>
                      <td>{c.name}</td>
                      <td style={{ textAlign: "right" }}>{c.clicks}</td>
                      <td style={{ textAlign: "right" }}>{c.conversions}</td>
                      <td style={{ textAlign: "right" }} className="qx-amount positive">{inr(c.earnings)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </div>
        </>
      )}
    </AppShell>
  );
}
