import { useEffect, useState, type CSSProperties } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ErrorBanner } from "../components/Common";
import { formatIST } from "../lib/ist";

interface OfflineCampaign { campaign_id: string; name: string; events: string[] }
interface ClickRow { click_id: string; publisher_id: string; clicked_at: string | null; status: "approved" | "pending" | "rejected" }
interface ApproveResult { results: { click_id: string; result: string; detail?: string }[]; approved: number }

const RESULT_TEXT: Record<string, string> = {
  approved: "Approved", already_approved: "Already approved", rejected_final: "Rejected earlier (final)",
  not_found: "Not found in this campaign", error: "Error",
};

const chipStyle = (on: boolean): CSSProperties => ({
  padding: "8px 14px", borderRadius: 999, cursor: "pointer", fontSize: 14, fontWeight: 600,
  border: `1px solid ${on ? "var(--accent-primary)" : "var(--border)"}`,
  background: on ? "var(--accent-soft)" : "transparent", color: on ? "var(--accent-primary-text)" : "var(--text)",
});

/** Settle offline events from the advertiser's report: type the DigiSNR click ids and approve. */
export function OfflineReportPage() {
  const [campaigns, setCampaigns] = useState<OfflineCampaign[]>([]);
  const [campaignId, setCampaignId] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);     // events to approve (used when there are 2+)
  const [viewEvent, setViewEvent] = useState("");         // event whose clicks are listed (used when there are 2+)
  const [ids, setIds] = useState("");
  const [rows, setRows] = useState<ClickRow[]>([]);
  const [outcome, setOutcome] = useState<ApproveResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<OfflineCampaign[]>("/admin/conversion-review/offline/campaigns")
      .then((r) => setCampaigns(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load campaigns"));
  }, []);

  const selected = campaigns.find((c) => c.campaign_id === campaignId);
  const events = selected?.events ?? [];
  const single = events.length === 1;
  // With one offline event there is nothing to choose: it is used automatically and no picker is shown.
  const activeView = single ? events[0] : viewEvent;
  const approveTargets = single ? events : chosen;

  function loadRows() {
    if (!campaignId || !activeView) { setRows([]); return; }
    api.get<{ items: ClickRow[] }>("/admin/conversion-review/offline/clicks", { campaign_id: campaignId, event_name: activeView, page_size: 100 })
      .then((r) => setRows(r.data.items))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load clicks"));
  }
  useEffect(loadRows, [campaignId, activeView]);

  function toggleChosen(ev: string) {
    setOutcome(null);
    setChosen((cur) => (cur.includes(ev) ? cur.filter((x) => x !== ev) : [...cur, ev]));
  }

  async function approve() {
    const list = ids.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);
    if (!list.length || !approveTargets.length) return;
    setBusy(true); setError(null); setOutcome(null);
    try {
      // Batches of 25 per request; one pass per selected event.
      const BATCH = 25;
      const merged: ApproveResult = { results: [], approved: 0 };
      for (const ev of approveTargets) {
        for (let i = 0; i < list.length; i += BATCH) {
          const chunk = list.slice(i, i + BATCH);
          const r = await api.post<ApproveResult>("/admin/conversion-review/offline/approve", { campaign_id: campaignId, event_name: ev, click_ids: chunk });
          merged.results.push(...r.data.results.map((x) => ({ ...x, click_id: `${x.click_id} (${ev})` })));
          merged.approved += r.data.approved;
          setOutcome({ ...merged, results: [...merged.results] }); // live progress
        }
      }
      setIds(""); loadRows();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Approval failed");
    } finally { setBusy(false); }
  }

  async function mark(clickId: string, status: "pending" | "rejected") {
    setError(null);
    try {
      await api.post("/admin/conversion-review/offline/mark", { campaign_id: campaignId, event_name: activeView, click_id: clickId, status });
      loadRows();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed");
    }
  }

  return (
    <AppShell title="Offline Report">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Offline Report</div>
          <div className="qx-page-subtitle">
            For offline events. Paste the DigiSNR click ids from the advertiser's report and approve — the publisher is paid
            and their postback fires. Clicks not in the report stay Pending, or mark them Rejected.
          </div>
        </div>
      </div>
      <ErrorBanner message={error} />

      <div className="qx-card" style={{ marginBottom: 18 }}>
        <div className="qx-field">
          <label htmlFor="off-camp">Campaign</label>
          <select id="off-camp" className="qx-select" value={campaignId}
            onChange={(e) => { setCampaignId(e.target.value); setChosen([]); setViewEvent(""); setOutcome(null); }}>
            <option value="">Select campaign…</option>
            {campaigns.map((c) => <option key={c.campaign_id} value={c.campaign_id}>{c.name}</option>)}
          </select>
          {campaigns.length === 0 && <div className="qx-hint">No campaign has an offline event yet.</div>}
        </div>

        {selected && events.length >= 2 && (
          <>
            <div className="qx-field">
              <label>Which events are in this report? (select one or more to approve)</label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {events.map((ev) => (
                  <button key={ev} type="button" style={chipStyle(chosen.includes(ev))} aria-pressed={chosen.includes(ev)}
                    onClick={() => toggleChosen(ev)}>{chosen.includes(ev) ? "✓ " : ""}{ev}</button>
                ))}
              </div>
            </div>
            <div className="qx-field">
              <label>Show clicks for</label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {events.map((ev) => (
                  <button key={ev} type="button" style={chipStyle(activeView === ev)} aria-pressed={activeView === ev}
                    onClick={() => { setViewEvent(ev); setOutcome(null); }}>{ev}</button>
                ))}
              </div>
            </div>
          </>
        )}

        <div className="qx-field">
          <label htmlFor="off-ids">DigiSNR click ids from the advertiser's report (one per line or comma-separated)</label>
          <textarea id="off-ids" className="qx-textarea" placeholder="DGSNR1866FK69G4" value={ids} onChange={(e) => setIds(e.target.value)} />
        </div>
        <button className="qx-btn qx-btn-primary" disabled={busy || !approveTargets.length || !ids.trim()} onClick={approve}>
          {busy ? "Approving…" : approveTargets.length > 1 ? `Approve ${approveTargets.length} events & credit publishers` : "Approve & credit publishers"}
        </button>

        {outcome && (
          <div className="qx-callout" style={{ marginTop: 14 }}>
            <div className="qx-callout-title">{outcome.approved} approved</div>
            {outcome.results.filter((r) => r.result !== "approved").map((r, i) => (
              <div key={`${r.click_id}-${i}`}><code>{r.click_id}</code> — {RESULT_TEXT[r.result] ?? r.result}{r.detail ? ` (${r.detail})` : ""}</div>
            ))}
          </div>
        )}
      </div>

      {activeView && (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead><tr><th>click_id</th><th>Publisher id</th><th>Clicked (IST)</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={5} style={{ color: "var(--text-muted)" }}>No clicks yet.</td></tr>}
              {rows.map((r) => (
                <tr key={r.click_id}>
                  <td><code>{r.click_id}</code></td>
                  <td>{r.publisher_id}</td>
                  <td>{formatIST(r.clicked_at)}</td>
                  <td style={{ textTransform: "capitalize" }}>{r.status}</td>
                  <td style={{ display: "flex", gap: 6 }}>
                    <button className="qx-btn qx-btn-sm" disabled={r.status !== "pending"} onClick={() => mark(r.click_id, "pending")}>Pending</button>
                    <button className="qx-btn qx-btn-sm" disabled={r.status === "rejected"} onClick={() => mark(r.click_id, "rejected")}>Rejected</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AppShell>
  );
}
