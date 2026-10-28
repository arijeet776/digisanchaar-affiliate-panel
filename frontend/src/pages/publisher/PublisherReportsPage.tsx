import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { formatDateTime, formatLocation, formatPayout } from "../../api/format";
import { AppShell } from "../../components/AppShell";
import { EmptyState, ErrorBanner, Pagination, StatusBadge } from "../../components/Common";
import { IconSearch } from "../../components/Icons";
import { ReportsView } from "../../components/ReportsView";
import { ExportCenter } from "./ExportCenter";

type Tab = "conversion" | "clicks" | "campaign" | "export" | "postback" | "performance";

// The Sidebar (Report group) is the primary navigation: the active report is
// derived from the URL (?tab=...), so every sidebar item changes the page.
const TABS: { key: Tab; label: string; subtitle: string }[] = [
  { key: "conversion", label: "Conversion Report", subtitle: "Every conversion with its actual event, status and payout." },
  { key: "clicks", label: "Clicks Report", subtitle: "Every tracked click with location, IP and your P1–P10 parameters." },
  { key: "campaign", label: "Campaign Report", subtitle: "Clicks, conversions and payout per campaign." },
  { key: "export", label: "Export Center", subtitle: "Export clicks and conversions data in the background." },
  { key: "postback", label: "Postback Logs", subtitle: "Delivery attempts of your postbacks to your server." },
  { key: "performance", label: "Performance Report", subtitle: "Performance broken down by event." },
];
const P_COLS = Array.from({ length: 10 }, (_, i) => ({ key: `p${i + 1}`, label: `P${i + 1}` }));

const PAGE_SIZE = 20;

type PValues = { p1: string | null; p2: string | null; p3: string | null; p4: string | null; p5: string | null; p6: string | null; p7: string | null; p8: string | null; p9: string | null; p10: string | null };
interface ConvEvent {
  conversion_id: string; event: string | null; status: string | null; approval_status: string;
  payout: number | null; currency: string | null; conversion_created_at: string; postback_received_at: string | null;
}
// One row per DigiSNR click ID; `events` are the badges (Install, Register, KYC, ...).
interface Conv extends PValues {
  digisnr_click_id: string; campaign_id: string; campaign_name: string | null; date: string;
  country: string | null; state: string | null; city: string | null; ip: string | null;
  events: ConvEvent[]; total_payout: number; currency: string | null;
}
interface Click extends PValues {
  digisnr_click_id: string; campaign_id: string; campaign_name: string | null; click_created_at: string;
  ip: string | null; country: string | null; state: string | null; city: string | null;
}
interface EventSummaryRow { event: string | null; conversions: number; payout: number; currency: string }
interface Campaign { campaign_id: string; name: string }
type Range = "today" | "7" | "30" | "90" | "";
const RANGES: { key: Range; label: string }[] = [
  { key: "today", label: "Today" }, { key: "7", label: "Last 7 days" }, { key: "30", label: "Last 30 days" }, { key: "90", label: "Last 90 days" },
];
function rangeToDates(r: Range): { date_from?: string; date_to?: string } {
  if (!r) return {};
  const now = new Date();
  const from = new Date(now);
  if (r === "today") from.setHours(0, 0, 0, 0); else from.setDate(from.getDate() - Number(r));
  return { date_from: from.toISOString(), date_to: now.toISOString() };
}
function Filters({ range, setRange, campaign, setCampaign, campaigns, search, setSearch, placeholder }: {
  range: Range; setRange: (r: Range) => void; campaign: string; setCampaign: (c: string) => void;
  campaigns: Campaign[]; search: string; setSearch: (s: string) => void; placeholder: string;
}) {
  return (
    <div className="qx-filter-card">
      <div className="qx-search">
        <IconSearch width={18} height={18} />
        <input className="qx-input" placeholder={placeholder} value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <div className="qx-filter-row">
        <select className="qx-select" value={campaign} onChange={(e) => setCampaign(e.target.value)} aria-label="Filter by campaign">
          <option value="">All Campaigns</option>
          {campaigns.map((c) => <option key={c.campaign_id} value={c.campaign_id}>{c.name}</option>)}
        </select>
        <div className="qx-range-pills">
          {RANGES.map((r) => <button key={r.key} type="button" className={range === r.key ? "active" : ""} onClick={() => setRange(range === r.key ? "" : r.key)}>{r.label}</button>)}
        </div>
      </div>
    </div>
  );
}
function ColumnChooser({ all, visible, setVisible }: { all: { key: string; label: string }[]; visible: string[]; setVisible: (v: string[]) => void }) {
  return (
    <div className="qx-checkgrid">
      {all.map((c) => (
        <label className="qx-check" key={c.key}>
          <input type="checkbox" checked={visible.includes(c.key)}
            onChange={() => setVisible(visible.includes(c.key) ? visible.filter((k) => k !== c.key) : [...visible, c.key])} />
          {c.label}
        </label>
      ))}
    </div>
  );
}
interface Outbound {
  outbound_id: string; conversion_id: string; campaign_id: string; event: string | null; direction: string; url: string | null; full_url: string | null;
  attempt_count: number; retries: number; final_status: string; created_at: string;
  http_status: number | null; latency_ms: number | null; last_error: string | null;
}

function PrevNext({ page, hasMore, onChange }: { page: number; hasMore: boolean; onChange: (p: number) => void }) {
  return (
    <div className="qx-pagination">
      <span>Page {page}</span>
      <div className="qx-pagination-controls">
        <button className="qx-btn qx-btn-sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>Previous</button>
        <button className="qx-btn qx-btn-sm" disabled={!hasMore} onClick={() => onChange(page + 1)}>Next</button>
      </div>
    </div>
  );
}

interface Col<T> { key: string; label: string; render?: (r: T) => React.ReactNode }

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function RowTable<T extends Record<string, any>>({
  rows, cols, keyField, loading, empty,
}: { rows: T[]; cols: Col<T>[]; keyField: string; loading: boolean; empty: string }) {
  if (loading) return <div className="qx-empty-state">Loading…</div>;
  if (rows.length === 0) return <EmptyState message={empty} />;
  return (
    <div className="qx-table-wrap">
      <table className="qx-table">
        <thead><tr>{cols.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={String(r[keyField])}>
              {cols.map((c) => <td key={c.key}>{c.render ? c.render(r) : String(r[c.key] ?? "—")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PublisherReportsPage() {
  const [searchParams] = useSearchParams();
  const rawTab = searchParams.get("tab") as Tab | null;
  const tab: Tab = rawTab && TABS.some((t) => t.key === rawTab) ? rawTab : "conversion";
  const tabMeta = TABS.find((t) => t.key === tab)!;
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);

  const [conversions, setConversions] = useState<Conv[] | null>(null);
  const [clicks, setClicks] = useState<Click[] | null>(null);
  const [outbound, setOutbound] = useState<Outbound[] | null>(null);
  const [outboundTotal, setOutboundTotal] = useState(0);
  const [events, setEvents] = useState<EventSummaryRow[] | null>(null);
  const [viewUrl, setViewUrl] = useState<string | null>(null);

  const [range, setRange] = useState<Range>("");
  const [campaign, setCampaign] = useState("");
  const [search, setSearch] = useState("");
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [convCols, setConvCols] = useState<string[]>(["date", "click", "campaign", "location", "ip", "event", "status", "payout"]);
  const [clickCols, setClickCols] = useState<string[]>(["date", "click", "campaign", "location", "ip", "p1"]);
  const [kpi, setKpi] = useState<{ clicks: number; conversions: number; earnings: number; pending: number } | null>(null);

  // Switching report (sidebar) resets paging/filters-in-flight/errors and stale rows.
  useEffect(() => { setPage(1); setError(null); setConversions(null); setClicks(null); setOutbound(null); }, [tab]);
  useEffect(() => { setPage(1); setError(null); }, [range, campaign, search]);
  useEffect(() => {
    api.get<Campaign[]>("/publisher/campaigns").then((r) => setCampaigns(r.data)).catch(() => undefined);
    api.get<{ clicks: number; stats: { lifetime: { conversions: number; earnings: number; pending: number } } }>("/publisher/dashboard")
      .then((r) => setKpi({ clicks: r.data.clicks, ...r.data.stats.lifetime })).catch(() => undefined);
  }, []);

  useEffect(() => {
    const dates = rangeToDates(range);
    const fail = (e: unknown) => setError(e instanceof ApiError ? e.message : "Failed to load");
    if (tab === "conversion") {
      api.get<Conv[]>("/publisher/conversions", { page, page_size: PAGE_SIZE, campaign_id: campaign || undefined, search: search || undefined, ...dates })
        .then((r) => setConversions(r.data)).catch(fail);
      api.get<EventSummaryRow[]>("/publisher/conversions/event-summary", { campaign_id: campaign || undefined, ...dates })
        .then((r) => setEvents(r.data)).catch(() => setEvents([]));
    } else if (tab === "clicks") {
      api.get<Click[]>("/publisher/clicks", { page, page_size: PAGE_SIZE, campaign_id: campaign || undefined, search: search || undefined, ...dates })
        .then((r) => setClicks(r.data)).catch(fail);
    } else if (tab === "postback") {
      api.get<{ items: Outbound[]; total: number }>("/publisher/postback-logs", { page, page_size: PAGE_SIZE, campaign_id: campaign || undefined })
        .then((r) => { setOutbound(r.data.items); setOutboundTotal(r.data.total); }).catch(fail);
    }
  }, [tab, page, range, campaign, search]);

  const campName = (id: string, name: string | null) => name ?? campaigns.find((c) => c.campaign_id === id)?.name ?? id;
  const pCell = (r: PValues, k: string) => (r as unknown as Record<string, string | null>)[k] ?? "";

  return (
    <AppShell title="Reports">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title" data-testid="report-title">{tabMeta.label}</div>
          <div className="qx-page-subtitle">{tabMeta.subtitle}</div>
        </div>
      </div>
      <ErrorBanner message={error} />

      {tab === "conversion" && kpi && (
        <div className="qx-stat-grid" style={{ marginBottom: 14 }}>
          <div className="qx-stat-card"><div className="qx-stat-label">Total Conversions</div><div className="qx-stat-value">{kpi.conversions}</div></div>
          <div className="qx-stat-card"><div className="qx-stat-label">Confirmed Earnings</div><div className="qx-stat-value">₹{kpi.earnings.toLocaleString("en-IN")}</div></div>
          <div className="qx-stat-card"><div className="qx-stat-label">Awaiting Company Report</div><div className="qx-stat-value">₹{kpi.pending.toLocaleString("en-IN")}</div></div>
        </div>
      )}
      {tab === "clicks" && kpi && (
        <div className="qx-stat-grid" style={{ marginBottom: 14 }}>
          <div className="qx-stat-card"><div className="qx-stat-label">Total Clicks</div><div className="qx-stat-value">{kpi.clicks}</div></div>
          <div className="qx-stat-card"><div className="qx-stat-label">Conversion Rate</div><div className="qx-stat-value">{kpi.clicks ? ((kpi.conversions / kpi.clicks) * 100).toFixed(2) : "0.00"}%</div></div>
        </div>
      )}

      {tab === "conversion" && (
        <>
          {events && events.length > 0 && (
            <div className="qx-event-summary" data-testid="event-summary" aria-label="Conversions by event">
              {events.map((e) => (
                <div className="qx-event-card" key={e.event ?? "none"} data-testid={`event-card-${e.event ?? "unspecified"}`}>
                  <div className="name">{e.event ?? "Unspecified event"}</div>
                  <div className="meta">{e.conversions} conversion{e.conversions === 1 ? "" : "s"}</div>
                  <div className="amt">{formatPayout(e.payout, e.currency)}</div>
                </div>
              ))}
            </div>
          )}
          <Filters range={range} setRange={setRange} campaign={campaign} setCampaign={setCampaign} campaigns={campaigns}
            search={search} setSearch={setSearch} placeholder="Search conversions by click ID…" />
          <ColumnChooser visible={convCols} setVisible={setConvCols} all={[
            { key: "date", label: "Date" }, { key: "click", label: "Click ID" }, { key: "campaign", label: "Campaign" },
            { key: "location", label: "Location" }, { key: "ip", label: "IP" }, { key: "event", label: "Event/Goal" },
            { key: "status", label: "Status" }, { key: "payout", label: "Payout" }, ...P_COLS]} />
          <RowTable<Conv>
            rows={conversions ?? []} loading={conversions === null} empty="No conversions yet."
            keyField="digisnr_click_id"
            cols={([
              { key: "date", label: "Date", render: (r) => formatDateTime(r.date) },
              { key: "click", label: "Click ID", render: (r) => <span className="qx-code-pill">{r.digisnr_click_id}</span> },
              { key: "campaign", label: "Campaign", render: (r) => campName(r.campaign_id, r.campaign_name) },
              { key: "location", label: "Location", render: (r) => formatLocation(r.city, r.state, r.country) },
              { key: "ip", label: "IP", render: (r) => r.ip ?? "" },
              { key: "event", label: "Event/Goal", render: (r) => (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {r.events.map((e) => (
                    <span key={e.conversion_id} className="qx-tag ok" data-testid="conv-event">
                      {e.event ?? "Unspecified"} · {formatPayout(e.payout, e.currency)}
                    </span>
                  ))}
                </div>
              ) },
              { key: "status", label: "Status", render: (r) => (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {r.events.map((e) => <StatusBadge key={e.conversion_id} status={e.approval_status} />)}
                </div>
              ) },
              { key: "payout", label: "Payout", render: (r) => formatPayout(r.total_payout, r.currency) },
              ...P_COLS.map((c) => ({ key: c.key, label: c.label, render: (r: Conv) => pCell(r, c.key) })),
            ] as Col<Conv>[]).filter((c) => convCols.includes(c.key))}
          />
          <PrevNext page={page} hasMore={(conversions?.length ?? 0) === PAGE_SIZE} onChange={setPage} />
        </>
      )}

      {tab === "clicks" && (
        <>
          <Filters range={range} setRange={setRange} campaign={campaign} setCampaign={setCampaign} campaigns={campaigns}
            search={search} setSearch={setSearch} placeholder="Search clicks by click ID or IP…" />
          <ColumnChooser visible={clickCols} setVisible={setClickCols} all={[
            { key: "date", label: "Date" }, { key: "click", label: "Click ID" }, { key: "campaign", label: "Campaign" },
            { key: "location", label: "Location" }, { key: "ip", label: "IP" }, ...P_COLS]} />
          <RowTable<Click>
            rows={clicks ?? []} loading={clicks === null} empty="No clicks yet."
            keyField="digisnr_click_id"
            cols={([
              { key: "date", label: "Date", render: (r) => formatDateTime(r.click_created_at) },
              { key: "click", label: "Click ID", render: (r) => <span className="qx-code-pill">{r.digisnr_click_id}</span> },
              { key: "campaign", label: "Campaign", render: (r) => campName(r.campaign_id, r.campaign_name) },
              { key: "location", label: "Location", render: (r) => formatLocation(r.city, r.state, r.country) },
              { key: "ip", label: "IP", render: (r) => r.ip ?? "" },
              ...P_COLS.map((c) => ({ key: c.key, label: c.label, render: (r: Click) => pCell(r, c.key) })),
            ] as Col<Click>[]).filter((c) => clickCols.includes(c.key))}
          />
          <PrevNext page={page} hasMore={(clicks?.length ?? 0) === PAGE_SIZE} onChange={setPage} />
        </>
      )}

      {tab === "campaign" && (
        <ReportsView key="campaign" endpoint="/admin/reports/publisher/summary" showFinancials={false} showManagerFilter={false}
          groupOptions={[{ value: "campaign", label: "By Campaign" }, { value: "event", label: "By Event" }]}
          campaignsUrl="/publisher/campaigns" />
      )}

      {tab === "performance" && (
        <ReportsView key="performance" endpoint="/admin/reports/publisher/summary" showFinancials={false} showManagerFilter={false}
          groupOptions={[{ value: "event", label: "By Event" }, { value: "campaign", label: "By Campaign" }]}
          campaignsUrl="/publisher/campaigns" />
      )}

      {tab === "postback" && (
        <>
          <div className="qx-filter-card"><div className="qx-filter-row">
            <select className="qx-select" value={campaign} onChange={(e) => setCampaign(e.target.value)} aria-label="Filter by campaign">
              <option value="">All Campaigns</option>
              {campaigns.map((c) => <option key={c.campaign_id} value={c.campaign_id}>{c.name}</option>)}
            </select>
          </div></div>
          <RowTable<Outbound>
            rows={outbound ?? []} loading={outbound === null} empty="No postback deliveries found yet."
            keyField="outbound_id"
            cols={[
              { key: "created_at", label: "Time", render: (r) => formatDateTime(r.created_at) },
              { key: "direction", label: "Direction", render: (r) => <span className="qx-chip">{r.direction}</span> },
              { key: "conversion_id", label: "Conversion", render: (r) => <span className="qx-code-pill">{r.conversion_id}</span> },
              { key: "campaign_id", label: "Campaign", render: (r) => campName(r.campaign_id, null) },
              { key: "event", label: "Event", render: (r) => r.event ?? "" },
              { key: "url", label: "URL", render: (r) => <span className="qx-url-cell" title={r.url ?? ""}>{r.url ?? ""}</span> },
              { key: "http", label: "HTTP", render: (r) => r.http_status ?? (r.last_error ? "—" : "") },
              { key: "attempt_count", label: "Attempt", render: (r) => `${r.attempt_count} (${r.retries} ${r.retries === 1 ? "retry" : "retries"})` },
              { key: "final_status", label: "Result", render: (r) => r.final_status === "delivered"
                ? <span className="qx-status-ok">Delivered</span>
                : <span className="qx-status-bad" title={r.last_error ?? undefined}>Failed</span> },
              { key: "latency_ms", label: "Latency", render: (r) => <span className="qx-latency">{r.latency_ms != null ? `${r.latency_ms}ms` : "—"}</span> },
              { key: "view", label: "Full URL", render: (r) => (
                <button className="qx-btn qx-btn-sm" disabled={!r.full_url} onClick={() => setViewUrl(r.full_url)}>View</button>
              ) },
            ]}
          />
          <Pagination page={page} pageSize={PAGE_SIZE} total={outboundTotal} onChange={setPage} />
          {viewUrl && (
            <div onClick={() => setViewUrl(null)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16, zIndex: 1000 }}>
              <div onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Postback URL" style={{ background: "var(--surface)", color: "var(--text)", borderRadius: 16, padding: 20, width: "min(640px, 100%)", maxHeight: "80vh", overflow: "auto", position: "relative" }}>
                <button type="button" aria-label="Close" onClick={() => setViewUrl(null)} style={{ position: "absolute", top: 10, right: 10, width: 28, height: 28, borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)", cursor: "pointer", fontSize: 16, lineHeight: 1 }}>×</button>
                <div style={{ fontWeight: 700, marginBottom: 10 }}>Postback URL (full)</div>
                <div style={{ fontFamily: "monospace", fontSize: 13, wordBreak: "break-all", background: "var(--surface-2, transparent)", border: "1px solid var(--border)", borderRadius: 10, padding: 12 }}>{viewUrl}</div>
              </div>
            </div>
          )}
        </>
      )}

      {tab === "export" && <ExportCenter campaigns={campaigns} />}
    </AppShell>
  );
}
