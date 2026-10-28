import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ErrorBanner } from "../components/Common";
import { formatIST } from "../lib/ist";

interface ClickRow {
  campaign_title: string | null;
  click_id: string;
  publisher_id: string;
  campaign_id: string;
  clicked_at: string | null;
  ip?: string | null;
  advertiser_click_id?: string | null;
}
interface ClickReport { items: ClickRow[]; total: number; show_admin_columns: boolean }

const PAGE_SIZE = 50;

/** One row per click. Everyone sees the DigiSNR click id and the IP; only the Super Admin also sees the advertiser's click id. */
export function ClickReportPage() {
  const [data, setData] = useState<ClickReport | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [error, setError] = useState<string | null>(null);

  function load(p = page) {
    api.get<ClickReport>("/click-reports", {
      page: p, page_size: PAGE_SIZE,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo ? { date_to: dateTo } : {}),
    })
      .then((r) => { setData(r.data); setError(null); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load click report"));
  }
  useEffect(() => { load(page); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [page]);

  const admin = !!data?.show_admin_columns;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <AppShell title="Click Report">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Click Report</div>
          <div className="qx-page-subtitle">Every click with its DigiSNR click id. Times are in IST.</div>
        </div>
      </div>
      <ErrorBanner message={error} />

      <form className="qx-row" style={{ marginBottom: 14 }} onSubmit={(e) => { e.preventDefault(); setPage(1); load(1); }}>
        <div className="qx-field"><label htmlFor="cr-search">Click id</label>
          <input id="cr-search" className="qx-input" placeholder="DGSNR…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <div className="qx-field"><label htmlFor="cr-from">From</label>
          <input id="cr-from" className="qx-input" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></div>
        <div className="qx-field"><label htmlFor="cr-to">To</label>
          <input id="cr-to" className="qx-input" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></div>
        <div className="qx-field" style={{ alignSelf: "flex-end" }}><button className="qx-btn qx-btn-primary" type="submit">Apply</button></div>
      </form>

      <div className="qx-table-wrap">
        <table className="qx-table">
          <thead>
            <tr>
              <th>Campaign</th><th>click_id</th>
              {admin && <th>Advertiser click id</th>}
              <th>IP</th>
              <th>Date &amp; time (IST)</th><th>Publisher id</th><th>Campaign id</th>
            </tr>
          </thead>
          <tbody>
            {data && data.items.length === 0 && <tr><td colSpan={admin ? 7 : 6} style={{ color: "var(--text-muted)" }}>No clicks found.</td></tr>}
            {data?.items.map((r) => (
              <tr key={r.click_id}>
                <td>{r.campaign_title ?? "—"}</td>
                <td><code>{r.click_id}</code></td>
                {admin && <td>{r.advertiser_click_id ? <code>{r.advertiser_click_id}</code> : "—"}</td>}
                <td>{r.ip ?? "—"}</td>
                <td>{formatIST(r.clicked_at)}</td>
                <td>{r.publisher_id}</td>
                <td>{r.campaign_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12 }}>
        <button className="qx-btn qx-btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</button>
        <span>Page {page} of {pages}{data ? ` · ${data.total} clicks` : ""}</span>
        <button className="qx-btn qx-btn-sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Next</button>
      </div>
    </AppShell>
  );
}
