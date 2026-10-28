import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { getAccessToken } from "../api/tokenStore";
import { ErrorBanner, KpiCard } from "./Common";
import { IconFinancial, IconLink, IconReports, IconUsers } from "./Icons";

interface ReportRow {
  key: string;
  clicks: number;
  conversions: number;
  revenue?: number;
  payout: number;
  margin?: number;
  conversion_rate: number | null;
}

interface Report {
  totals: {
    clicks: number;
    conversions: number;
    revenue?: number;
    payout: number;
    margin?: number;
    conversion_rate: number | null;
  };
  rows: ReportRow[];
  group_by: string;
}

interface CampaignOption {
  campaign_id: string;
  name: string;
}

const inr = (v?: number | null) => (v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN")}`);

export function ReportsView({
  endpoint,
  showFinancials,
  showManagerFilter,
  groupOptions,
  campaignsUrl,
  exportUrl,
}: {
  endpoint: string;
  showFinancials: boolean;
  showManagerFilter: boolean;
  groupOptions: { value: string; label: string }[];
  campaignsUrl: string;
  exportUrl?: string;
}) {
  const [report, setReport] = useState<Report | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignOption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [managerId, setManagerId] = useState("");
  const [event, setEvent] = useState("");
  const [groupBy, setGroupBy] = useState(groupOptions[0].value);

  const load = useCallback(() => {
    const params: Record<string, string> = { group_by: groupBy };
    if (dateFrom) params.date_from = `${dateFrom}T00:00:00Z`;
    if (dateTo) params.date_to = `${dateTo}T23:59:59Z`;
    if (campaignId) params.campaign_id = campaignId;
    if (showManagerFilter && managerId) params.manager_id = managerId;
    if (event) params.event = event;
    api
      .get<Report>(endpoint, params)
      .then((r) => setReport(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load report"));
  }, [endpoint, groupBy, dateFrom, dateTo, campaignId, managerId, event, showManagerFilter]);

  useEffect(load, [load]);

  useEffect(() => {
    api.get<CampaignOption[]>(campaignsUrl, { page_size: 100 }).then((r) => setCampaigns(r.data)).catch(() => {});
  }, [campaignsUrl]);

  async function exportCsv() {
    if (!exportUrl) return;
    const params = new URLSearchParams({ group_by: groupBy });
    if (dateFrom) params.set("date_from", `${dateFrom}T00:00:00Z`);
    if (dateTo) params.set("date_to", `${dateTo}T23:59:59Z`);
    if (campaignId) params.set("campaign_id", campaignId);
    if (event) params.set("event", event);
    const apiBase = import.meta.env.VITE_API_BASE_URL || "/api/v1";
    const resp = await fetch(`${apiBase}${exportUrl}?${params}`, {
      headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
    });
    const blob = await resp.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "digisanchaar-report.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  const t = report?.totals;

  return (
    <div data-testid="reports-view">
      <div className="qx-card" style={{ marginBottom: 16 }}>
        <div className="qx-row" style={{ marginBottom: 0 }}>
          <div className="qx-field" style={{ marginBottom: 0 }}>
            <label>From</label>
            <input type="date" className="qx-input" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} data-testid="report-date-from" />
          </div>
          <div className="qx-field" style={{ marginBottom: 0 }}>
            <label>To</label>
            <input type="date" className="qx-input" value={dateTo} onChange={(e) => setDateTo(e.target.value)} data-testid="report-date-to" />
          </div>
          <div className="qx-field" style={{ marginBottom: 0 }}>
            <label>Campaign</label>
            <select className="qx-select" value={campaignId} onChange={(e) => setCampaignId(e.target.value)} data-testid="report-campaign-filter">
              <option value="">All campaigns</option>
              {campaigns.map((c) => (
                <option key={c.campaign_id} value={c.campaign_id}>{c.name}</option>
              ))}
            </select>
          </div>
          {showManagerFilter && (
            <div className="qx-field" style={{ marginBottom: 0 }}>
              <label>Manager ID</label>
              <input className="qx-input" placeholder="e.g. AM97578" value={managerId} onChange={(e) => setManagerId(e.target.value)} data-testid="report-manager-filter" />
            </div>
          )}
          <div className="qx-field" style={{ marginBottom: 0 }}>
            <label>Event</label>
            <input className="qx-input" placeholder="e.g. Install" value={event} onChange={(e) => setEvent(e.target.value)} data-testid="report-event-filter" />
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center", flexWrap: "wrap" }}>
          <span className="qx-kpi-label" style={{ margin: 0 }}>Group by</span>
          {groupOptions.map((g) => (
            <button
              key={g.value}
              type="button"
              aria-pressed={groupBy === g.value}
              className={`qx-tab${groupBy === g.value ? " active" : ""}`}
              onClick={() => setGroupBy(g.value)}
              data-testid={`report-group-${g.value}`}
            >
              {g.label}
            </button>
          ))}
          {exportUrl && (
            <button className="qx-btn qx-btn-sm" style={{ marginLeft: "auto" }} onClick={exportCsv} data-testid="report-export-csv">
              Export CSV
            </button>
          )}
        </div>
      </div>

      <ErrorBanner message={error} />

      {t && (
        <>
          <div className="qx-kpi-grid">
            <KpiCard label="Clicks" metric={{ available: true, value: t.clicks, reason: null }} icon={IconLink} />
            <KpiCard label="Conversions" metric={{ available: true, value: t.conversions, reason: null }} icon={IconReports} />
            {showFinancials && <KpiCard label="Revenue" metric={{ available: true, value: t.revenue ?? 0, reason: null }} format={(v) => inr(v) ?? "—"} icon={IconFinancial} />}
            <KpiCard label="Payout" metric={{ available: true, value: t.payout, reason: null }} format={(v) => inr(v) ?? "—"} icon={IconFinancial} />
            {showFinancials && <KpiCard label="Margin" metric={{ available: true, value: t.margin ?? 0, reason: null }} format={(v) => inr(v) ?? "—"} icon={IconFinancial} />}
            <KpiCard label="Conversion Rate" metric={{ available: true, value: t.conversion_rate ?? 0, reason: null }} format={(v) => `${v}%`} icon={IconUsers} />
          </div>

          <div className="qx-table-wrap" data-testid="report-table">
            <table className="qx-table">
              <thead>
                <tr>
                  <th style={{ textTransform: "capitalize" }}>{report?.group_by}</th>
                  <th>Clicks</th>
                  <th>Conversions</th>
                  {showFinancials && <th>Revenue</th>}
                  <th>Payout</th>
                  {showFinancials && <th>Margin</th>}
                  <th>CR %</th>
                </tr>
              </thead>
              <tbody>
                {report?.rows.length === 0 && (
                  <tr><td colSpan={7} style={{ color: "var(--text-muted)" }}>No data for the selected filters.</td></tr>
                )}
                {report?.rows.map((row) => (
                  <tr key={row.key}>
                    <td>{row.key}</td>
                    <td>{row.clicks}</td>
                    <td>{row.conversions}</td>
                    {showFinancials && <td className="qx-amount">{inr(row.revenue)}</td>}
                    <td className="qx-amount positive">{inr(row.payout)}</td>
                    {showFinancials && <td className="qx-amount">{inr(row.margin)}</td>}
                    <td>{row.conversion_rate !== null ? `${row.conversion_rate}%` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
