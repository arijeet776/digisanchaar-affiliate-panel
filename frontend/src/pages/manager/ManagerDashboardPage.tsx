import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../components/AppShell";
import { ErrorBanner, KpiCard, LoadingState } from "../../components/Common";
import { IconCampaign, IconFinancial, IconLink, IconReports, IconUsers } from "../../components/Icons";

interface ManagerDashboard {
  manager_id: string;
  display_name: string;
  publishers: { total: number; active: number; pending: number; rejected: number };
  available_campaigns: number;
  clicks: { available: boolean; value: number | null; reason: string };
  conversions: { available: boolean; value: number | null; reason: string };
  earnings: { available: boolean; value: number | null; reason: string };
}

export function ManagerDashboardPage() {
  const [data, setData] = useState<ManagerDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ManagerDashboard>("/manager/dashboard")
      .then((r) => setData(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load dashboard"));
  }, []);

  return (
    <AppShell title="Dashboard">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title" data-testid="manager-dashboard-title">
            {data ? `Welcome, ${data.display_name}` : "Manager Dashboard"}
          </div>
          <div className="qx-page-subtitle">
            {data && (
              <>
                Manager ID: <strong data-testid="manager-id">{data.manager_id}</strong> — scoped to your assigned publishers only
              </>
            )}
          </div>
        </div>
      </div>

      <ErrorBanner message={error} />
      {!data && !error && <LoadingState variant="kpis" rows={8} />}

      {data && (
        <>
          <div className="qx-kpi-grid">
            <KpiCard label="My Publishers" metric={{ available: true, value: data.publishers.total, reason: null }} icon={IconUsers} />
            <KpiCard label="Active Publishers" metric={{ available: true, value: data.publishers.active, reason: null }} icon={IconUsers} />
            <KpiCard label="Pending Approval" metric={{ available: true, value: data.publishers.pending, reason: null }} icon={IconUsers} />
            <KpiCard label="Available Campaigns" metric={{ available: true, value: data.available_campaigns, reason: null }} icon={IconCampaign} />
            <KpiCard label="Clicks" metric={data.clicks} icon={IconLink} />
            <KpiCard label="Conversions" metric={data.conversions} icon={IconReports} />
            <KpiCard label="Earnings" metric={data.earnings} format={(v) => `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`} icon={IconFinancial} />
          </div>

          <div className="qx-section-title">Quick actions</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Link to="/manager/publishers" className="qx-btn qx-btn-primary" data-testid="manager-qa-invite">Manage Publishers</Link>
            <Link to="/manager/campaigns" className="qx-btn" data-testid="manager-qa-campaigns">View Campaigns</Link>
          </div>
        </>
      )}
    </AppShell>
  );
}
