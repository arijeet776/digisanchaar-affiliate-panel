import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { EmptyState, ErrorBanner, Pagination, StatusBadge } from "../components/Common";

interface CampaignRow {
  campaign_id: string;
  name: string;
  advertiser_name: string | null;
  platform: string | null;
  status: string;
  created_at: string;
  config_version: number;
}

const PAGE_SIZE = 20;

export function CampaignsPage() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const search = params.get("search") ?? "";
  const page = parseInt(params.get("page") ?? "1", 10);

  const [rows, setRows] = useState<CampaignRow[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<CampaignRow[]>("/admin/campaigns", {
        status: status || undefined,
        search: search || undefined,
        page,
        page_size: PAGE_SIZE,
      })
      .then((r) => {
        setRows(r.data);
        setTotal(r.totalCount ?? r.data.length);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load campaigns"));
  }, [status, search, page]);

  return (
    <AppShell title="Campaigns">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Campaign Management</div>
          <div className="qx-page-subtitle">Create, review and manage campaigns, payouts and tracking links.</div>
        </div>
        <Link to="/campaigns/new" className="qx-btn qx-btn-primary">
          + Create Campaign
        </Link>
      </div>

      <ErrorBanner message={error} />

      <div className="qx-row" style={{ marginBottom: 14 }}>
        <input
          className="qx-input"
          placeholder="Search by name or campaign ID…"
          defaultValue={search}
          onKeyDown={(e) => {
            if (e.key === "Enter") setParams({ status, search: e.currentTarget.value, page: "1" });
          }}
        />
        <select className="qx-select" value={status} onChange={(e) => setParams({ status: e.target.value, search, page: "1" })}>
          <option value="">All statuses</option>
          <option value="draft">Draft</option>
          <option value="active">Active</option>
          <option value="paused">Paused</option>
          <option value="ended">Ended</option>
          <option value="purged">Purged</option>
        </select>
      </div>

      {rows.length === 0 ? (
        <EmptyState message="No campaigns yet." />
      ) : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead>
              <tr>
                <th>Campaign</th>
                <th>Advertiser</th>
                <th>Platform</th>
                <th>Status</th>
                <th>Version</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.campaign_id}>
                  <td>
                    <Link to={`/campaigns/${c.campaign_id}`}>{c.name}</Link>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{c.campaign_id}</div>
                  </td>
                  <td>{c.advertiser_name ?? "—"}</td>
                  <td>{c.platform ?? "—"}</td>
                  <td><StatusBadge status={c.status} /></td>
                  <td>v{c.config_version}</td>
                  <td>{new Date(c.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onChange={(p) => setParams({ status, search, page: String(p) })} />
    </AppShell>
  );
}
