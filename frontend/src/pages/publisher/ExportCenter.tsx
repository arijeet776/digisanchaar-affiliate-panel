import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import { downloadAuthed } from "../../api/download";
import { formatDateTime } from "../../api/format";
import { EmptyState, ErrorBanner, Modal } from "../../components/Common";

type Kind = "clicks" | "conversions";
interface Job {
  job_id: string; kind: Kind; format: "csv" | "json"; status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
  records: number | null; truncated: boolean; error: string | null; created_at: string;
  filters: { campaign_id?: string | null; date_from?: string | null; date_to?: string | null; unique_ip?: boolean };
}
interface Campaign { campaign_id: string; name: string }

const GUIDE: { key: string; tab: string; title: string; body: React.ReactNode }[] = [
  { key: "what", tab: "What is the Export Center?", title: "What is the Export Center?",
    body: <p>The Export Center lets you request and download CSV or JSON files of your own clicks and conversions so you can analyse your traffic offline.</p> },
  { key: "why", tab: "Why background exports?", title: "Why use background exports?",
    body: <ul><li><strong>No waiting:</strong> the file is prepared on our servers — you can leave the page.</li><li><strong>Complete data:</strong> tables show one page at a time; an export gives you the whole range in one file.</li><li><strong>Download history:</strong> re-download earlier exports from the list.</li></ul> },
  { key: "how", tab: "How it works", title: "How background exporting works",
    body: <ol><li><strong>Choose</strong> Clicks or Conversions.</li><li><strong>Submit</strong> a date range, optional campaign and format.</li><li><strong>Download</strong> once the status shows COMPLETED.</li></ol> },
  { key: "criteria", tab: "What you provide", title: "What criteria you can provide",
    body: <ul><li><strong>Date range:</strong> up to 90 days per export.</li><li><strong>Format:</strong> CSV for Excel / Google Sheets, JSON for developer tools.</li><li><strong>Campaign:</strong> pick one, or leave blank for all.</li><li><strong>Unique IP (clicks):</strong> keep one row per IP address.</li></ul> },
];

function GuideModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState(GUIDE[0].key);
  const cur = GUIDE.find((g) => g.key === tab) ?? GUIDE[0];
  return (
    <Modal title="Export Center Guide" onClose={onClose}>
      <div className="qx-tab-row" role="tablist">
        {GUIDE.map((g) => (
          <button key={g.key} role="tab" aria-selected={tab === g.key} className={`qx-tab ${tab === g.key ? "active" : ""}`} onClick={() => setTab(g.key)}>{g.tab}</button>
        ))}
      </div>
      <h3 style={{ margin: "4px 0 8px" }}>{cur.title}</h3>
      <div className="qx-guide-body">{cur.body}</div>
      <p className="qx-hint" style={{ marginTop: 12 }}>Large exports can take a little longer. Each file holds up to 20,000 rows; narrow the date range for more.</p>
    </Modal>
  );
}

function ExportModal({ kind, campaigns, onClose, onCreated }: { kind: Kind; campaigns: Campaign[]; onClose: () => void; onCreated: () => void }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [campaign, setCampaign] = useState("");
  const [format, setFormat] = useState<"csv" | "json">("csv");
  const [unique, setUnique] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true); setError(null);
    try {
      await api.post("/publisher/exports", {
        kind, format, campaign_id: campaign || undefined, unique_ip: kind === "clicks" ? unique : false,
        date_from: from ? new Date(from).toISOString() : undefined,
        date_to: to ? new Date(to).toISOString() : undefined,
      });
      onCreated(); onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start export");
    } finally { setBusy(false); }
  }
  return (
    <Modal title={`Export ${kind === "clicks" ? "Clicks" : "Conversions"}`} onClose={onClose}>
      <ErrorBanner message={error} />
      <div className="qx-field"><label htmlFor="ex-from">From date &amp; time</label>
        <input id="ex-from" className="qx-input" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
      <div className="qx-field"><label htmlFor="ex-to">To date &amp; time</label>
        <input id="ex-to" className="qx-input" type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} /></div>
      <div className="qx-field"><label htmlFor="ex-camp">Campaign</label>
        <select id="ex-camp" className="qx-select" value={campaign} onChange={(e) => setCampaign(e.target.value)}>
          <option value="">All campaigns</option>
          {campaigns.map((c) => <option key={c.campaign_id} value={c.campaign_id}>{c.name}</option>)}
        </select></div>
      <div className="qx-field"><label htmlFor="ex-fmt">Format</label>
        <select id="ex-fmt" className="qx-select" value={format} onChange={(e) => setFormat(e.target.value as "csv" | "json")}>
          <option value="csv">CSV (Excel / Google Sheets)</option><option value="json">JSON</option>
        </select></div>
      {kind === "clicks" && (
        <label className="qx-check"><input type="checkbox" checked={unique} onChange={(e) => setUnique(e.target.checked)} /> Unique IP only</label>
      )}
      <div className="qx-modal-actions">
        <button className="qx-btn" onClick={onClose}>Cancel</button>
        <button className="qx-btn qx-btn-primary" disabled={busy} onClick={submit} data-testid="export-submit">{busy ? "Submitting…" : "Submit"}</button>
      </div>
    </Modal>
  );
}

export function ExportCenter({ campaigns }: { campaigns: Campaign[] }) {
  const [kind, setKind] = useState<Kind>("clicks");
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showExport, setShowExport] = useState(false);
  const [showGuide, setShowGuide] = useState(false);

  const load = useCallback(() => {
    api.get<Job[]>("/publisher/exports", { kind })
      .then((r) => setJobs(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load exports"));
  }, [kind]);

  useEffect(() => { setJobs(null); setError(null); load(); }, [load]);
  // Poll only while something is still being prepared.
  const busy = (jobs ?? []).some((j) => j.status === "PENDING" || j.status === "PROCESSING");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [busy, load]);

  async function download(j: Job) {
    try { await downloadAuthed(`/publisher/exports/${j.job_id}/download`, `digisnr-${j.kind}-${j.job_id}.${j.format}`); }
    catch { setError("Download failed"); }
  }
  const chips = (j: Job) => {
    const out: string[] = [];
    if (j.filters.unique_ip) out.push("Unique IP");
    if (j.filters.date_from) out.push(`From ${new Date(j.filters.date_from).toLocaleDateString()}`);
    if (j.filters.date_to) out.push(`To ${new Date(j.filters.date_to).toLocaleDateString()}`);
    if (j.filters.campaign_id) out.push(campaigns.find((c) => c.campaign_id === j.filters.campaign_id)?.name ?? "Campaign");
    out.push(j.format.toUpperCase());
    return out;
  };

  return (
    <div data-testid="export-center">
      <p className="qx-page-subtitle" style={{ marginBottom: 12 }}>Export clicks and conversions data in the background.</p>
      <button className="qx-btn" onClick={() => setShowGuide(true)} data-testid="export-guide">View Guide</button>
      <div className="qx-segmented" role="tablist" aria-label="Export type">
        {(["clicks", "conversions"] as Kind[]).map((k) => (
          <button key={k} role="tab" aria-selected={kind === k} className={kind === k ? "active" : ""} onClick={() => setKind(k)} data-testid={`export-tab-${k}`}>
            {k === "clicks" ? "Clicks" : "Conversions"}
          </button>
        ))}
      </div>
      <button className="qx-btn qx-btn-primary" style={{ width: "100%" }} onClick={() => setShowExport(true)} data-testid="export-open">
        + Export {kind === "clicks" ? "Clicks" : "Conversions"}
      </button>
      <ErrorBanner message={error} />
      <div className="qx-export-bar">
        <span>{jobs ? `${jobs.length} export(s)` : "Loading…"}</span>
        <button className="qx-btn qx-btn-sm" onClick={load}>Refresh</button>
      </div>
      {jobs && jobs.length === 0 ? (
        <EmptyState message="No exports yet. Click Export to prepare your first file." />
      ) : jobs && (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead><tr><th>Job ID</th><th>Filters</th><th>Status</th><th>Records</th><th>Created</th><th>Actions</th></tr></thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.job_id} data-testid={`export-row-${j.job_id}`}>
                  <td><span className="qx-code-pill">{j.job_id.slice(0, 8)}…</span></td>
                  <td><div className="qx-chip-row">{chips(j).map((c) => <span key={c} className="qx-chip">{c}</span>)}</div></td>
                  <td><span className={`qx-badge ${j.status === "COMPLETED" ? "active" : j.status === "FAILED" ? "rejected" : "pending"}`}>{j.status}</span></td>
                  <td>{j.records ?? ""}{j.truncated ? " (capped)" : ""}</td>
                  <td>{formatDateTime(j.created_at)}</td>
                  <td>{j.status === "COMPLETED"
                    ? <button className="qx-btn qx-btn-sm" onClick={() => download(j)} data-testid={`export-download-${j.job_id}`}>Download</button>
                    : j.status === "FAILED" ? <span className="qx-hint">{j.error}</span> : <span className="qx-hint">Preparing…</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {showExport && <ExportModal kind={kind} campaigns={campaigns} onClose={() => setShowExport(false)} onCreated={load} />}
      {showGuide && <GuideModal onClose={() => setShowGuide(false)} />}
    </div>
  );
}
