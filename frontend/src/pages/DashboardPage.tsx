import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ErrorBanner, KpiCard, LoadingState } from "../components/Common";
import {
  IconCampaign, IconFinancial, IconLink, IconManager, IconReports, IconUsers,
} from "../components/Icons";

interface Metric {
  available: boolean;
  value: number | null;
  reason: string | null;
}

interface DashboardData {
  kpis: Record<string, Metric>;
  pending_approvals: { managers: number; publishers: number };
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<DashboardData>("/admin/dashboard")
      .then((r) => setData(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load dashboard"));
  }, []);

  return (
    <AppShell title="Dashboard">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Network Overview</div>
          <div className="qx-page-subtitle">Live counts from Managers, Publishers, and Campaigns.</div>
        </div>
      </div>

      <ErrorBanner message={error} />
      {!data && !error && <LoadingState variant="kpis" rows={8} />}

      {data && (
        <>
          <div className="qx-kpi-grid">
            <KpiCard label="Total Managers" metric={data.kpis.total_managers} icon={IconManager} />
            <KpiCard label="Active Managers" metric={data.kpis.active_managers} icon={IconManager} />
            <KpiCard label="Total Publishers" metric={data.kpis.total_publishers} icon={IconUsers} />
            <KpiCard label="Active Publishers" metric={data.kpis.active_publishers} icon={IconUsers} />
            <KpiCard label="Active Campaigns" metric={data.kpis.active_campaigns} icon={IconCampaign} />
            <KpiCard label="Total Campaigns" metric={data.kpis.total_campaigns} icon={IconCampaign} />
            <KpiCard label="Total Clicks" metric={data.kpis.total_clicks} icon={IconLink} />
            <KpiCard label="Successful Events" metric={data.kpis.successful_events} icon={IconReports} />
            <KpiCard label="Network Revenue" metric={data.kpis.network_revenue} format={(v) => `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`} icon={IconFinancial} />
            <KpiCard label="Publisher Payout" metric={data.kpis.publisher_payout} format={(v) => `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`} icon={IconFinancial} />
            <KpiCard label="Network Margin" metric={data.kpis.network_margin} format={(v) => `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`} icon={IconFinancial} />
          </div>

          <div className="qx-section-title">Pending approvals</div>
          <div className="qx-row">
            <Link to="/managers?status=pending" className="qx-card" style={{ display: "block", textDecoration: "none" }}>
              <div className="qx-kpi-label">Manager applications</div>
              <div className="qx-kpi-value">{data.pending_approvals.managers}</div>
            </Link>
            <Link to="/publishers?status=pending" className="qx-card" style={{ display: "block", textDecoration: "none" }}>
              <div className="qx-kpi-label">Publisher applications</div>
              <div className="qx-kpi-value">{data.pending_approvals.publishers}</div>
            </Link>
          </div>

          <div className="qx-section-title">Quick actions</div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Link to="/managers" className="qx-btn">Add Manager</Link>
            <Link to="/publishers" className="qx-btn">Review Publishers</Link>
            <Link to="/campaigns/new" className="qx-btn qx-btn-primary">Create Campaign</Link>
            <Link to="/reports" className="qx-btn">View Reports</Link>
          </div>
        </>
      )}
    </AppShell>
  );
}
