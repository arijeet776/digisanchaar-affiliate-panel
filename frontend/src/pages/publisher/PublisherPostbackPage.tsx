import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../components/AppShell";
import { ErrorBanner } from "../../components/Common";
import { SuccessPopup } from "../../components/SuccessPopup";
import { IconCheck, IconCopy, IconLink } from "../../components/Icons";

// The macro vocabulary is served by the backend (single source of truth shared
// with server-side validation): GET /admin/postback/macros. Sample values below
// only power the clearly-labelled "example" URL preview - they are not data.
interface MacroDef { token: string; label: string; group: string; description: string }
const SAMPLES: Record<string, string> = {
  click_id: "DGSNR9F8E7D6C5B", campaign_id: "CMP1A2B3C", campaign_name: "Sample Campaign", publisher_id: "4821",
  event: "Install", status: "success", date: "2026-09-27", date_time: "2026-09-27T10:00:00Z",
  ip: "203.0.113.7", country: "India", country_code: "IN", state: "Maharashtra", city: "Mumbai", payout: "12.4",
  ...Object.fromEntries(Array.from({ length: 10 }, (_, i) => [`p${i + 1}`, `sub${i + 1}`])),
};

interface PublisherConfig {
  configured: boolean; url_template?: string; version?: number | null; enabled?: boolean;
  macros_selected?: string[]; updated_at?: string | null;
}
interface TestResult { http_status: number | null; error: string | null; latency_ms: number }

export function PublisherPostbackPage() {
  const [sp] = useSearchParams();
  const campaignId = sp.get("campaign_id");
  const [config, setConfig] = useState<PublisherConfig | null>(null);
  const [macros, setMacros] = useState<MacroDef[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [url, setUrl] = useState("");
  const [active, setActive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);
  const [copied, setCopied] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const scope = campaignId ? { campaign_id: campaignId } : {};
  const isGlobal = !campaignId;

  useEffect(() => {
    api.get<MacroDef[]>("/admin/postback/macros").then((r) => setMacros(r.data)).catch(() => undefined);
  }, []);

  function load() {
    api.get<PublisherConfig>(isGlobal ? "/admin/postback/global-config" : "/admin/postback/publisher-config", scope)
      .then((r) => { setConfig(r.data); if (r.data.url_template) setUrl(r.data.url_template); if (r.data.enabled != null) setActive(r.data.enabled); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load postback settings"));
  }
  useEffect(load, [campaignId]);

  async function save() {
    setBusy(true); setError(null); setSaved(false);
    try {
      if (isGlobal) await api.put("/admin/postback/global-config", { url, enabled: active });
      else await api.put("/admin/postback/publisher-config", { url, enabled: active, ...scope });
      setSaved(true); load();
    } catch (err) { setError(err instanceof ApiError ? err.message : "Failed to save"); }
    finally { setBusy(false); }
  }

  async function runTest() {
    setError(null); setTest(null);
    try { setTest((await api.post<TestResult>("/admin/postback/publisher-config/test", { url, ...scope })).data); }
    catch (err) { setError(err instanceof ApiError ? err.message : "Test failed"); }
  }

  async function removeGlobal() {
    setError(null);
    try {
      await api.delete("/admin/postback/global-config");
      setUrl(""); setConfig({ configured: false }); setConfirmDelete(false); setSaved(false);
    } catch (err) { setError(err instanceof ApiError ? err.message : "Failed to delete"); }
  }

  function insert(macro: string) {
    const el = input.current;
    const start = el?.selectionStart ?? url.length;
    const end = el?.selectionEnd ?? url.length;
    setUrl(url.slice(0, start) + macro + url.slice(end));
    setTimeout(() => el?.focus(), 0);
  }

  const preview = useMemo(() => {
    let out = url;
    for (const m of macros) out = out.split(`{${m.token}}`).join(encodeURIComponent(SAMPLES[m.token] ?? ""));
    return out;
  }, [url, macros]);

  const groups = useMemo(() => {
    const g = new Map<string, MacroDef[]>();
    for (const m of macros) g.set(m.group, [...(g.get(m.group) ?? []), m]);
    return [...g.entries()];
  }, [macros]);

  return (
    <AppShell title="Account">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title qx-page-title-xl" style={{ fontSize: 30 }}>{campaignId ? "Campaign Postback" : "Global Postback Settings"}</div>
          <div className="qx-page-subtitle">
            {campaignId ? `Postback URL for campaign #${campaignId}. It overrides your global postback for this campaign.`
              : "Configure a root postback URL that triggers on all campaigns and conversion events."}
          </div>
        </div>
      </div>
      <ErrorBanner message={error} />
      <SuccessPopup open={saved} onClose={() => setSaved(false)} title="Postback saved" testId="postback-config-saved">
        Configuration saved{config?.version ? ` (version ${config.version})` : ""}. New conversions use it; previous deliveries are unchanged.
      </SuccessPopup>

      <div className="qx-panel">
        <div className="qx-panel-body">
          <div className="qx-info-box">
            <h4>How Root Global Postback Works</h4>
            When a user conversion occurs, the postback service resolves the optimal target URL. If no campaign-specific postback is found, it falls back to this Global Postback — only one postback is ever sent per conversion.
            Use tokens like <b>{"{event}"}</b> to receive the event that converted (e.g. Install, Register, KYC, Trade) and <b>{"{payout}"}</b> for your payout. Missing values are sent blank.
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <label htmlFor="pb-url" style={{ fontWeight: 700 }}>{campaignId ? "Postback URL" : "Global Postback URL"}</label>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 10, color: "var(--text-secondary)" }}>
              Active <button type="button" className={`qx-toggle${active ? " on" : ""}`} aria-pressed={active} onClick={() => setActive((a) => !a)} />
            </span>
          </div>
          <input id="pb-url" ref={input} className="qx-input" style={{ height: 50, borderRadius: 14 }} value={url}
            placeholder="https://your-server.example/postback?cid={click_id}&status={status}"
            onChange={(e) => setUrl(e.target.value)} data-testid="publisher-postback-url-input" />

          <div style={{ fontWeight: 700, marginTop: 22 }}>Available Postback Macro Tokens</div>
          <div className="qx-panel-sub" style={{ margin: "4px 0 12px" }}>
            Macro tokens are dynamic placeholders wrapped in curly braces (like <code>{"{click_id}"}</code>). When a conversion occurs, DigiSanchaar replaces them with real conversion details before calling your server. Tap a token to insert it.
          </div>
          {groups.map(([group, items]) => (
            <div key={group}>
              <div className="qx-checkgroup-label" style={{ margin: "14px 0 8px" }}>{group}</div>
              <div className="qx-macro-cards" data-testid={`macro-grid-${group.replace(/[^a-z]+/gi, "-").toLowerCase()}`}>
                {items.map((m) => (
                  <button type="button" className="qx-macro-card" key={m.token} onClick={() => insert(`{${m.token}}`)} title={m.description}>
                    <code>{`{${m.token}}`}</code><div>{m.label}</div>
                  </button>
                ))}
              </div>
            </div>
          ))}

          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 24, paddingTop: 20, borderTop: "1px solid var(--border)" }}>
            {isGlobal && config?.configured && (
              <button type="button" className="qx-btn qx-btn-danger" onClick={() => setConfirmDelete(true)} data-testid="global-postback-delete">Delete Global Config</button>
            )}
            <button type="button" className="qx-btn qx-btn-outline" disabled={!url.trim()} onClick={runTest}>▷ Test Postback URL</button>
            <button type="button" className="qx-btn qx-btn-primary" style={{ height: 46, borderRadius: 14, flex: 1, minWidth: 180 }}
              disabled={busy || !url.trim()} onClick={save} data-testid="publisher-postback-save">{busy ? "Saving…" : "Save Configuration"}</button>
          </div>
          {confirmDelete && (
            <div className="qx-info-box" role="alertdialog" style={{ marginTop: 14 }}>
              <b>Delete the Global Postback?</b> Conversions will stop sending to this URL (campaign-specific postbacks are unaffected). Previous deliveries and version history are kept.
              <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
                <button type="button" className="qx-btn qx-btn-danger" onClick={removeGlobal} data-testid="global-postback-delete-confirm">Delete</button>
                <button type="button" className="qx-btn" onClick={() => setConfirmDelete(false)}>Cancel</button>
              </div>
            </div>
          )}
          {test && (
            <div style={{ marginTop: 14 }}>
              {test.http_status && test.http_status < 400
                ? <span className="qx-status-ok"><IconCheck width={14} height={14} /> {test.http_status} Success · <span className="qx-latency">{test.latency_ms}ms</span></span>
                : <span className="qx-status-bad">{test.http_status ?? "Unreachable"} {test.error ?? ""}</span>}
            </div>
          )}
        </div>
      </div>

      <div className="qx-panel">
        <div className="qx-panel-head"><div className="qx-panel-icon"><IconLink width={20} height={20} /></div><div className="qx-panel-title">Live URL Ingestion Preview</div></div>
        <div className="qx-panel-body">
          <div className="qx-url-box" style={{ margin: 0 }}>{preview || "—"}</div>
          <div className="qx-panel-sub" style={{ marginTop: 10 }}>This is an example representing how your tracking receiver will see the request parameters during a standard client conversion process.</div>
        </div>
      </div>

      <div className="qx-panel">
        <div className="qx-hud-head">Connection HUD</div>
        <div className="qx-hud-row"><span>Status</span>{config?.configured && config.enabled ? <span className="qx-status-ok">ACTIVE</span> : <span className="qx-tag">NOT CONFIGURED</span>}</div>
        <div className="qx-hud-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
          <span>Ingestion Endpoint</span>
          <div className="qx-url-box" style={{ margin: 0, fontSize: 13, display: "flex", justifyContent: "space-between", gap: 10, color: "var(--text-primary)" }}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{config?.url_template ?? "—"}</span>
            {config?.url_template && <button type="button" className="qx-input-action" style={{ position: "static", transform: "none" }}
              onClick={async () => { await navigator.clipboard.writeText(config.url_template!); setCopied(true); setTimeout(() => setCopied(false), 1200); }}>
              {copied ? <IconCheck width={16} height={16} /> : <IconCopy width={16} height={16} />}</button>}
          </div>
        </div>
        {config?.configured && config.version && <div className="qx-hud-row"><span>Version</span><span>v{config.version}</span></div>}
        {config?.configured && config.updated_at && <div className="qx-hud-row"><span>Last updated</span><span data-testid="postback-updated-at">{new Date(config.updated_at).toLocaleString()}</span></div>}
        {config?.configured && (config.macros_selected?.length ?? 0) > 0 && (
          <div className="qx-hud-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
            <span>Macros in use</span>
            <div className="qx-chip-row">{config.macros_selected!.map((m) => <span className="qx-chip" key={m}>{`{${m}}`}</span>)}</div>
          </div>
        )}
      </div>

      <div className="qx-panel">
        <div className="qx-panel-head"><div className="qx-panel-icon"><IconLink width={20} height={20} /></div><div className="qx-panel-title">Macro Token Reference Guide</div></div>
        <div className="qx-panel-body">
          {macros.map((m) => (
            <div key={m.token} style={{ padding: "10px 0", borderTop: "1px solid var(--border)" }}>
              <code className="qx-tag" style={{ color: "var(--qx-accent)" }}>{`{${m.token}}`}</code>{" "}
              <span className="qx-hint">{m.label}</span>
              <div className="qx-panel-sub" style={{ marginTop: 6 }}>{m.description}{m.token === "click_id" ? " Mandatory for matching conversions — always DigiSanchaar's own click ID." : ""}</div>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
