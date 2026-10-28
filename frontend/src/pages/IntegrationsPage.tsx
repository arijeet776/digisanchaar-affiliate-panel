import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ErrorBanner, StatusBadge } from "../components/Common";

interface PlatformMeta {
  label: string;
  required: string[];
  optional: string[];
  methods: string[];
  verified: boolean;
  note?: string;
}

interface Endpoint {
  endpoint_id: string;
  campaign_id: string;
  platform: string;
  status: string;
  received_count: number;
  failure_count: number;
  last_received_at: string | null;
  created_at: string;
}

interface InboundLog {
  postback_id: string;
  platform: string;
  campaign_id: string;
  received_at: string;
  processing_status: string;
  event: string | null;
  status: string | null;
  digisnr_click_id: string | null;
  external_click_id: string | null;
  external_conversion_id: string | null;
  conversion_id: string | null;
  error: string | null;
}

interface CampaignOption {
  campaign_id: string;
  name: string;
}

export function IntegrationsPage() {
  const [platforms, setPlatforms] = useState<Record<string, PlatformMeta> | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignOption[]>([]);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [logs, setLogs] = useState<InboundLog[]>([]);
  const [platform, setPlatform] = useState("offer18");
  const [campaignId, setCampaignId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdUrl, setCreatedUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  function loadEndpoints() {
    api.get<Endpoint[]>("/admin/postback/endpoints").then((r) => setEndpoints(r.data)).catch(() => {});
    api.get<InboundLog[]>("/admin/postback/logs", { page_size: 20 }).then((r) => setLogs(r.data)).catch(() => {});
  }

  useEffect(() => {
    api.get<Record<string, PlatformMeta>>("/admin/postback/platforms")
      .then((r) => setPlatforms(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load platforms"));
    api.get<CampaignOption[]>("/admin/campaigns", { page_size: 100 })
      .then((r) => setCampaigns(r.data))
      .catch(() => {});
    loadEndpoints();
  }, []);

  async function createEndpoint(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setCreatedUrl(null);
    try {
      const r = await api.post<Endpoint & { inbound_url: string; advertiser_postback_url?: string }>("/admin/postback/endpoints", {
        campaign_id: campaignId,
        platform,
      });
      setCreatedUrl(r.data.advertiser_postback_url ?? r.data.inbound_url);
      loadEndpoints();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create endpoint");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(endpointId: string, action: "enable" | "disable") {
    try {
      await api.post(`/admin/postback/endpoints/${endpointId}/${action}`, {});
      loadEndpoints();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  }

  const meta = platforms?.[platform];

  return (
    <AppShell title="Postback Setup">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Postback Setup</div>
          <div className="qx-page-subtitle">
            Receive conversion events from external platforms. Create an endpoint, copy its URL, paste
            it into the platform's postback settings.
          </div>
        </div>
      </div>

      <ErrorBanner message={error} />

      <div className="qx-card" style={{ marginBottom: 18 }} data-testid="postback-setup-card">
        <form onSubmit={createEndpoint}>
          <div className="qx-row">
            <div className="qx-field">
              <label htmlFor="pb-platform">Platform</label>
              <select id="pb-platform" className="qx-select" value={platform} onChange={(e) => setPlatform(e.target.value)} data-testid="postback-platform-select">
                {platforms && Object.entries(platforms).map(([key, m]) => (
                  <option key={key} value={key}>{m.label}</option>
                ))}
              </select>
            </div>
            <div className="qx-field">
              <label htmlFor="pb-campaign">Campaign</label>
              <select id="pb-campaign" className="qx-select" value={campaignId} onChange={(e) => setCampaignId(e.target.value)} required data-testid="postback-campaign-select">
                <option value="">Select campaign…</option>
                {campaigns.map((c) => (
                  <option key={c.campaign_id} value={c.campaign_id}>{c.name} ({c.campaign_id})</option>
                ))}
              </select>
            </div>
          </div>

          {meta && (
            <div className="qx-callout" style={{ marginBottom: 14 }} data-testid="platform-meta">
              <div className="qx-callout-title">{meta.label} parameters · {meta.methods.join(" / ")}</div>
              Required: <code>{meta.required.join(", ")}</code>
              <br />
              Optional: <code>{meta.optional.join(", ")}</code>
              {meta.verified === false && (
                <div style={{ color: "var(--qx-warning)", marginTop: 6 }}>{meta.note}</div>
              )}
            </div>
          )}

          <button className="qx-btn qx-btn-primary" disabled={busy || !campaignId} type="submit" data-testid="create-endpoint-button">
            {busy ? "Creating…" : "Generate Inbound Postback URL"}
          </button>
        </form>

        {createdUrl && (
          <div style={{ marginTop: 16 }} data-testid="endpoint-created">
            <div className="qx-kpi-label">Postback URL — paste this into the advertiser panel (click id, event and title macros are already added)</div>
            <code className="qx-code" data-testid="endpoint-created-url">{createdUrl}</code>
            <div style={{ marginTop: 8 }}>
              <button
                className="qx-btn qx-btn-sm"
                data-testid="endpoint-copy-button"
                onClick={async () => {
                  await navigator.clipboard.writeText(createdUrl);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }}
              >
                {copied ? "Copied ✓" : "Copy URL"}
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="qx-section-title">Endpoints</div>
      <div className="qx-table-wrap" style={{ marginBottom: 18 }} data-testid="endpoints-table">
        <table className="qx-table">
          <thead>
            <tr><th>Platform</th><th>Campaign</th><th>Status</th><th>Received</th><th>Failures</th><th>Last received</th><th></th></tr>
          </thead>
          <tbody>
            {endpoints.length === 0 && (
              <tr><td colSpan={7} style={{ color: "var(--text-muted)" }}>No endpoints yet.</td></tr>
            )}
            {endpoints.map((e) => (
              <tr key={e.endpoint_id}>
                <td style={{ textTransform: "capitalize" }}>{e.platform}</td>
                <td>{e.campaign_id}</td>
                <td><StatusBadge status={e.status === "active" ? "active" : "paused"} /></td>
                <td>{e.received_count}</td>
                <td>{e.failure_count}</td>
                <td>{e.last_received_at ? new Date(e.last_received_at).toLocaleString() : "—"}</td>
                <td>
                  <button
                    className="qx-btn qx-btn-sm"
                    data-testid={`endpoint-toggle-${e.endpoint_id}`}
                    onClick={() => toggle(e.endpoint_id, e.status === "active" ? "disable" : "enable")}
                  >
                    {e.status === "active" ? "Disable" : "Enable"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="qx-section-title">Recent inbound postbacks</div>
      <div className="qx-table-wrap" data-testid="postback-logs-table">
        <table className="qx-table">
          <thead>
            <tr><th>Received</th><th>Platform</th><th>Event</th><th>Status</th><th>Result</th><th>Conversion</th><th>Click</th></tr>
          </thead>
          <tbody>
            {logs.length === 0 && (
              <tr><td colSpan={7} style={{ color: "var(--text-muted)" }}>No postbacks received yet.</td></tr>
            )}
            {logs.map((l) => (
              <tr key={l.postback_id}>
                <td>{new Date(l.received_at).toLocaleString()}</td>
                <td style={{ textTransform: "capitalize" }}>{l.platform}</td>
                <td>{l.event ?? "—"}</td>
                <td>{l.status ?? "—"}</td>
                <td><StatusBadge status={l.processing_status === "processed" ? "active" : l.processing_status === "duplicate" ? "paused" : "rejected"} /></td>
                <td>{l.conversion_id ?? "—"}</td>
                <td>{l.digisnr_click_id ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
