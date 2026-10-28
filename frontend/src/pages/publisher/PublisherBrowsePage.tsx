import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../components/AppShell";
import { CampaignTable } from "../../components/CampaignTable";
import { EmptyState, ErrorBanner, Pagination, StatusBadge } from "../../components/Common";
import { IconFilter, IconSearch } from "../../components/Icons";

interface Available {
  campaign_id: string; name: string; logo_url: string | null; tracking_only: boolean; status: string;
  approval_mode: "promote_immediately" | "requires_approval"; tracking_window_hours: number | null;
  max_payout: number | null; access_status: "pending" | "approved" | "rejected" | null; has_link: boolean;
}
interface Resp { items: Available[]; total: number; facets: { categories: string[]; countries: string[] } }
const PAGE_SIZE = 12;

export function PublisherBrowsePage() {
  const [data, setData] = useState<Resp | null>(null);
  const [page, setPage] = useState(1);
  const [f, setF] = useState({ search: "", category: "", mode: "", kind: "", country: "", sort: "newest" });
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof f, v: string) => { setPage(1); setF((p) => ({ ...p, [k]: v })); };

  useEffect(() => {
    api.get<Resp>("/campaign-access/available", {
      page, page_size: PAGE_SIZE, search: f.search || undefined, category: f.category || undefined,
      mode: f.mode || undefined, kind: f.kind || undefined, country: f.country || undefined, sort: f.sort,
    }).then((r) => setData(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load campaigns"));
  }, [page, f]);

  return (
    <AppShell title="Campaigns">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Available Campaigns</div>
          <div className="qx-page-subtitle">Browse and promote active in-house and direct network campaigns.</div>
        </div>
      </div>
      <ErrorBanner message={error} />
      <div className="qx-filter-card">
        <div className="qx-search">
          <IconSearch width={18} height={18} />
          <input className="qx-input" placeholder="Search campaigns by name or ID…" value={f.search} onChange={(e) => set("search", e.target.value)} aria-label="Search campaigns" />
        </div>
        <div className="qx-filter-row">
          <IconFilter width={18} height={18} style={{ color: "var(--text-muted)" }} />
          <select className="qx-select" value={f.category} onChange={(e) => set("category", e.target.value)} aria-label="Category">
            <option value="">All Categories</option>
            {data?.facets.categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select className="qx-select" value={f.mode} onChange={(e) => set("mode", e.target.value)} aria-label="Type">
            <option value="">All Types</option>
            <option value="promote_immediately">Promote Immediately</option>
            <option value="requires_approval">Requires Approval</option>
          </select>
          <select className="qx-select" value={f.kind} onChange={(e) => set("kind", e.target.value)} aria-label="Kind">
            <option value="">All Kinds</option>
            <option value="standard">Standard</option>
            <option value="shopping">Shopping</option>
            <option value="survey">Survey</option>
          </select>
          <select className="qx-select" value={f.country} onChange={(e) => set("country", e.target.value)} aria-label="Country">
            <option value="">All Countries</option>
            {data?.facets.countries.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select className="qx-select" value={f.sort} onChange={(e) => set("sort", e.target.value)} aria-label="Sort">
            <option value="newest">Newest First</option>
            <option value="oldest">Oldest First</option>
            <option value="payout">Highest Payout</option>
          </select>
        </div>
      </div>
      {!data ? <div className="qx-empty-state">Loading…</div> : data.items.length === 0 ? (
        <EmptyState message="No campaigns match your filters." />
      ) : (
        <CampaignTable
          rows={data.items}
          extraHead={["Payout", "Access"]}
          extraCell={(r) => {
            const c = r as Available;
            return [
              c.max_payout != null ? `₹${c.max_payout}` : "—",
              c.has_link ? <StatusBadge status="approved" /> : c.access_status ? <StatusBadge status={c.access_status} /> :
                <span className="qx-csub">{c.approval_mode === "requires_approval" ? "Approval required" : "Open"}</span>,
            ];
          }}
        />
      )}
      <Pagination page={page} pageSize={PAGE_SIZE} total={data?.total ?? 0} onChange={setPage} />
    </AppShell>
  );
}
