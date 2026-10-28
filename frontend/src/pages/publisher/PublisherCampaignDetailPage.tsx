import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../components/AppShell";
import { ErrorBanner } from "../../components/Common";
import {
  IconBack, IconCheck, IconClock, IconCopy, IconFinancial, IconGlobe, IconLayers, IconLink,
  IconReports, IconShield, IconTarget,
} from "../../components/Icons";

interface Tally { label: string; count: number }
interface Detail {
  campaign_id: string; name: string; status: string; logo_url: string | null; description: string | null;
  category: string | null; kind: string; tracking_only: boolean; countries: string[];
  approval_mode: "promote_immediately" | "requires_approval"; tracking_window_hours: number | null; reserved_slot: number | null;
  events: { event_name: string; payout: number; completion_source: string }[]; max_payout: number | null;
  access_status: "pending" | "approved" | "rejected" | null; tracking_url: string | null;
  analytics: { total_clicks: number; countries: number; by_os: Tally[]; by_browser: Tally[]; by_country: Tally[]; by_city: Tally[] };
  postback: { configured: boolean; url_template: string | null; enabled: boolean };
  postback_logs: { outbound_id: string; created_at: string; final_status: string; event: string | null; http_status: number | null; latency_ms: number | null }[];
}

function Panel({ icon, title, sub, children, action }: { icon: ReactNode; title: string; sub?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="qx-panel">
      <div className="qx-panel-head">
        <div className="qx-panel-icon">{icon}</div>
        <div style={{ flex: 1 }}>
          <div className="qx-panel-title">{title}</div>
          {sub && <div className="qx-panel-sub">{sub}</div>}
        </div>
        {action}
      </div>
      <div className="qx-panel-body">{children}</div>
    </div>
  );
}

function InfoRow({ label, value, icon }: { label: string; value: string; icon: ReactNode }) {
  return (
    <div className="qx-info-row">
      <div><div className="qx-info-label">{label}</div><div className="qx-info-value">{value}</div></div>
      <div className="qx-info-icon">{icon}</div>
    </div>
  );
}

function Tile({ title, items, icon }: { title: string; items: Tally[]; icon: ReactNode }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <div className="qx-analytics-tile">
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div className="qx-panel-icon" style={{ width: 42, height: 42 }}>{icon}</div>
        <div><div style={{ fontWeight: 700, fontSize: 17 }}>{title}</div>
          <div className="qx-info-label" style={{ margin: 0, letterSpacing: ".2em", fontSize: 11 }}>GLOBAL METRICS</div></div>
      </div>
      {items.length === 0 ? <div className="qx-dashed-empty">Waiting for ingestion...</div> : items.map((i) => (
        <div className="qx-bar-row" key={i.label}>
          <span style={{ width: 90 }}>{i.label}</span>
          <div className="bar"><span style={{ width: `${(i.count / max) * 100}%` }} /></div>
          <strong>{i.count}</strong>
        </div>
      ))}
    </div>
  );
}

export function PublisherCampaignDetailPage() {
  const { campaignId } = useParams();
  const navigate = useNavigate();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [params, setParams] = useState<string[]>(Array(10).fill(""));
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  function load() {
    api.get<Detail>(`/publisher/campaigns/${campaignId}`)
      .then((r) => setD(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load campaign"));
  }
  useEffect(load, [campaignId]);

  // {click_id} typed into any slot is expanded server-side to the DigiSNR click id.
  const finalUrl = useMemo(() => {
    if (!d?.tracking_url) return "";
    const q = params.map((v, i) => (v.trim() && i + 1 !== d.reserved_slot ? `p${i + 1}=${v.trim()}` : "")).filter(Boolean).join("&");
    if (!q) return d.tracking_url;
    return d.tracking_url + (d.tracking_url.includes("?") ? "&" : "?") + q;
  }, [d, params]);

  async function copy(text: string) {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  async function requestAccess() {
    setBusy(true); setError(null);
    try { await api.post(`/campaign-access/${campaignId}/access`); load(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Request failed"); }
    finally { setBusy(false); }
  }

  if (!d) return <AppShell title="Campaigns"><ErrorBanner message={error} />{!error && <div className="qx-empty-state">Loading…</div>}</AppShell>;

  const promoteNow = d.approval_mode === "promote_immediately";
  const hasLink = !!d.tracking_url;

  return (
    <AppShell title="Campaigns">
      <button className="qx-back" onClick={() => navigate(-1)}><IconBack width={16} height={16} /> Back</button>
      <ErrorBanner message={error} />

      <div className="qx-hero">
        {d.logo_url ? <img className="qx-clogo" style={{ width: 94, height: 94, borderRadius: 26 }} src={d.logo_url} alt="" /> : <div className="qx-clogo" style={{ width: 94, height: 94, borderRadius: 26, fontSize: 34 }}>{d.name.slice(0, 1)}</div>}
        <div className="qx-eyebrow">ELITE CAMPAIGN <small>—— REF #{d.campaign_id}</small></div>
        <div className="qx-hero-name">{d.name}</div>
        <div className="qx-hero-badges">
          <span className="qx-active-pill" style={{ padding: "5px 14px", fontSize: 13 }}>{d.status === "active" ? "Active" : "Paused"}</span>
          <span className="qx-outline-pill">{d.kind.toUpperCase()}</span>
          <span style={{ color: "var(--text-secondary)" }}>FIXED Rewards</span>
        </div>
        <Link to="/publisher/reports?tab=campaign" className="qx-btn qx-btn-primary qx-btn-lg">Analyze Performance</Link>
      </div>

      <div className="qx-info-rows">
        <InfoRow label="Earnings Potential" value={d.max_payout != null ? `₹${d.max_payout}` : "—"} icon={<IconFinancial width={22} height={22} />} />
        <InfoRow label="Approval Mode" value={promoteNow ? "Promote Immediately" : "Requires Approval"} icon={<IconShield width={22} height={22} />} />
        <InfoRow label="Tracking Time" value={d.tracking_window_hours ? `${d.tracking_window_hours} Hours` : "Instant"} icon={<IconClock width={22} height={22} />} />
        <InfoRow label="Categories" value={d.category ? "1 Categories" : "0 Categories"} icon={<IconLayers width={22} height={22} />} />
        <InfoRow label="Tracked Goals" value={`${d.events.length} Goals`} icon={<IconReports width={22} height={22} />} />
      </div>

      <Panel icon={<IconLink width={22} height={22} />} title="Your Tracking Link" sub="Use this personal link in your placements, creatives, and traffic sources."
        action={hasLink ? <button className="qx-btn" onClick={() => copy(finalUrl)}><IconCopy width={16} height={16} /> {copied ? "Copied ✓" : "Copy Link"}</button> : undefined}>
        {!hasLink ? (
          d.access_status === "pending" ? <div className="qx-dashed-empty">Access request pending. You'll get your link as soon as it's approved.</div>
            : d.access_status === "rejected" ? <div className="qx-dashed-empty">Your access request for this campaign was rejected.</div>
            : <button className="qx-btn qx-btn-primary qx-btn-lg" disabled={busy} onClick={requestAccess}>{promoteNow ? "Promote now" : "Request access"}</button>
        ) : (
          <div className="qx-terminal">
            <div className="qx-terminal-bar"><i style={{ background: "#ff5f57" }} /><i style={{ background: "#febc2e" }} /><i style={{ background: "#28c840" }} /> TRACKING_URL.TXT</div>
            <div className="qx-terminal-body">
              <div className="qx-eyebrow" style={{ margin: 0, fontSize: 12 }}>AFFILIATE TRACKING URL</div>
              <div className="qx-url-box" data-testid="detail-tracking-url">{finalUrl}</div>
              <button className="qx-btn qx-btn-block" style={{ color: "var(--qx-accent)" }} onClick={() => copy(finalUrl)}><IconCopy width={16} height={16} /> Copy Tracking Link</button>
            </div>
            <div className="qx-param-block">
              <div style={{ fontWeight: 700, fontSize: 17 }}>Parameter Configuration</div>
              <div className="qx-panel-sub" style={{ marginBottom: 10 }}>Append custom parameters to track campaigns. Type <code>{"{click_id}"}</code> in any slot and DigiSanchaar will put its own unique click ID there.</div>
              <span className="qx-tag" style={{ color: "var(--qx-accent)" }}>{d.reserved_slot ? 9 : 10} Slots Available</span>
              <div className="qx-param-grid" style={{ marginTop: 14 }}>
                {params.map((v, i) => (i + 1 === d.reserved_slot ? null : (
                  <div key={i}>
                    <div className="qx-param-label">P{i + 1}</div>
                    <input className="qx-input" placeholder={i < 2 ? `Sub ID ${i + 1}` : `Param ${i + 1}`} value={v}
                      onChange={(e) => setParams((p) => p.map((x, j) => (j === i ? e.target.value : x)))} />
                    {i === 0 && <button type="button" className="qx-tag" style={{ marginTop: 6, cursor: "pointer" }} onClick={() => setParams((p) => p.map((x, j) => (j === 0 ? "{click_id}" : x)))}>Use {"{click_id}"}</button>}
                  </div>
                )))}
              </div>
            </div>
          </div>
        )}
      </Panel>

      <Panel icon={<IconTarget width={22} height={22} />} title="Offer Guidelines & Rules" sub="Campaign guidelines, traffic requirements, and compliance rules.">
        <div style={{ whiteSpace: "pre-wrap", lineHeight: 2, fontSize: 16 }}>{d.description || "No specific guidelines were provided for this campaign."}</div>
        {d.countries.length > 0 && <div className="qx-tagrow">{d.countries.map((c) => <span className="qx-tag" key={c}>{c}</span>)}</div>}
      </Panel>

      <Panel icon={<IconReports width={22} height={22} />} title="Conversion Goals" sub="Events and payouts mapped to this campaign.">
        {d.events.map((e) => (
          <div className="qx-goal" key={e.event_name}>
            <div className="qx-goal-top">
              <div className="qx-goal-icon"><IconLink width={20} height={20} /></div>
              <div><div style={{ fontWeight: 700, fontSize: 18, textTransform: "capitalize" }}>{e.event_name.replace(/_/g, " ")}</div>
                <div className="qx-csub">Fixed Payout</div></div>
              <div className="qx-goal-amount">₹{e.payout}</div>
            </div>
            <div className="qx-tagrow"><span className="qx-tag">VALUE: <code>{e.event_name}</code></span><span className="qx-tag ok">Quota: Unlimited</span></div>
          </div>
        ))}
      </Panel>

      <Panel icon={<IconGlobe width={22} height={22} />} title="Click Analytics" sub={`${d.analytics.total_clicks} tracked clicks across ${d.analytics.countries} countries.`}>
        <div className="qx-analytics-tile" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div><div className="qx-info-label">AGGREGATE TRAFFIC</div><div className="qx-info-value" style={{ fontSize: 38 }}>{d.analytics.total_clicks}</div></div>
          <div className="qx-panel-icon" style={{ width: 84, height: 84 }}><IconGlobe width={30} height={30} /></div>
        </div>
        <Tile title="By OS" items={d.analytics.by_os} icon={<IconLayers width={20} height={20} />} />
        <Tile title="By Browser" items={d.analytics.by_browser} icon={<IconGlobe width={20} height={20} />} />
        <Tile title="By Country" items={d.analytics.by_country} icon={<IconTarget width={20} height={20} />} />
        <Tile title="By City" items={d.analytics.by_city} icon={<IconTarget width={20} height={20} />} />
      </Panel>

      <Panel icon={<IconLink width={22} height={22} />} title="Configured Postbacks" sub="Manage tracking URLs to receive callbacks for successful conversions."
        action={<Link className="qx-btn qx-btn-primary" to={`/publisher/postback?campaign_id=${d.campaign_id}`}>+ Add Postback</Link>}>
        {d.postback.configured ? (
          <div className="qx-url-box" style={{ margin: 0, fontSize: 13 }}>{d.postback.url_template}</div>
        ) : (
          <div style={{ textAlign: "center", padding: 24 }}>
            <div style={{ letterSpacing: ".18em", fontWeight: 700, color: "var(--text-secondary)" }}>NO POSTBACKS ADDED</div>
            <div className="qx-csub">Click the add button above to configure tracking</div>
          </div>
        )}
      </Panel>

      <Panel icon={<IconClock width={22} height={22} />} title="Recent Postback Delivery Logs" sub="History of postbacks sent to your server for this campaign.">
        {d.postback_logs.length === 0 ? <div style={{ textAlign: "center", color: "var(--text-muted)" }}>No postback logs found for this campaign yet.</div> : (
          <div className="qx-table-wrap"><table className="qx-table"><thead><tr><th>Time</th><th>Status</th><th>Latency</th></tr></thead><tbody>
            {d.postback_logs.map((l) => (
              <tr key={l.outbound_id}><td>{new Date(l.created_at).toLocaleString()}</td>
                <td>{l.final_status === "delivered" ? <span className="qx-status-ok"><IconCheck width={14} height={14} /> {l.http_status ?? 200} Success</span> : <span className="qx-status-bad">{l.http_status ?? "Failed"}</span>}</td>
                <td className="qx-latency">{l.latency_ms != null ? `${l.latency_ms}ms` : "—"}</td></tr>
            ))}
          </tbody></table></div>
        )}
      </Panel>

      <Panel icon={<IconShield width={22} height={22} />} title="Campaign Access" sub="Your current approval state and what it means for promotion.">
        <div className="qx-access-ok">
          <IconCheck width={22} height={22} />
          <div>
            <strong>{hasLink ? (promoteNow ? "Promote Immediately" : "Approved") : d.access_status === "pending" ? "Approval Pending" : promoteNow ? "Promote Immediately" : "Approval Required"}</strong>
            {hasLink ? "Your tracking link is ready to use." : promoteNow ? "No approval needed. Get your tracking link above." : "A manager must approve you before you can promote this campaign."}
          </div>
        </div>
      </Panel>

      <Panel icon={<IconFinancial width={22} height={22} />} title="Revenue Stream" sub="Earning potential based on your traffic quality.">
        <div className="qx-payout-card">
          <div className="lbl"><span>ESTIMATED PAYOUT</span><span className="live">LIVE</span></div>
          <div className="amt">{d.max_payout != null ? `₹${d.max_payout}` : "—"}</div>
          <div>Per successful fixed action</div>
        </div>
      </Panel>
    </AppShell>
  );
}
