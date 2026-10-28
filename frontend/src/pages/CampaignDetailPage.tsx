import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ErrorBanner, Modal, StatusBadge } from "../components/Common";
import { SuccessPopup } from "../components/SuccessPopup";

interface PurgeCategory {
  collection: string;
  label: string;
  count: number;
}

interface PurgePreview {
  campaign_id: string;
  campaign_name: string;
  status: string;
  eligible: boolean;
  eligibility_reason: string | null;
  categories: PurgeCategory[];
  total_purgeable_records: number;
}

interface PurgeResult {
  purge_id: string;
  status: string;
  campaign_id: string;
  campaign_name: string;
  deleted_counts: Record<string, number>;
  total_deleted: number;
  verification: {
    campaign_records_remaining: Record<string, number>;
    all_purgeable_records_removed: boolean;
    unrelated_totals_unchanged: boolean;
    campaign_tombstone_present: boolean;
    audit_record_written: boolean;
  };
  message: string;
}

interface CampaignDetail {
  campaign_id: string;
  status: string;
  status_reason: string | null;
  status_reason_type: string | null;
  created_at: string;
  updated_at: string;
  config_version: number;
  config_effective_from: string;
  config: {
    name: string;
    advertiser_name: string | null;
    advertiser_tracking_url: string | null;
    logo_url: string | null;
    description: string | null;
    platform: string | null;
    postback_platform: string;
    postback_config: Record<string, string>;
    payout_min: number | null;
    payout_max: number | null;
    daily_cap: number | null;
    overall_cap: number | null;
    approval_mode?: string;
    tracking_window_hours?: number | null;
    events: { event_name: string; payout: number; completion_source: string }[];
  };
}

interface VersionSummary {
  version: number;
  effective_from: string;
  apply_scope: string;
  created_by: string;
  created_at: string;
  name: string;
}

export function CampaignDetailPage() {
  const { campaignId = "" } = useParams();
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [history, setHistory] = useState<VersionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pauseModalOpen, setPauseModalOpen] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [purgeOpen, setPurgeOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  function load() {
    api
      .get<CampaignDetail>(`/admin/campaigns/${campaignId}`)
      .then((r) => setCampaign(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load campaign"));
    api
      .get<VersionSummary[]>(`/admin/campaigns/${campaignId}/history`)
      .then((r) => setHistory(r.data))
      .catch(() => setHistory([]));
  }

  useEffect(load, [campaignId]);

  async function lifecycleAction(action: "activate" | "resume" | "end") {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/admin/campaigns/${campaignId}/${action}`);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    } finally {
      setBusy(false);
      setConfirmEnd(false);
    }
  }

  async function pause(reason: string) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/admin/campaigns/${campaignId}/pause`, { reason });
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    } finally {
      setBusy(false);
      setPauseModalOpen(false);
    }
  }

  if (!campaign) {
    return (
      <AppShell title="Campaign">
        <ErrorBanner message={error} />
        {!error && <div className="qx-empty-state">Loading…</div>}
      </AppShell>
    );
  }

  const c = campaign.config;

  return (
    <AppShell title={c.name}>
      <Link to="/campaigns" style={{ fontSize: 12.5 }}>← Back to Campaigns</Link>
      <ErrorBanner message={error} />

      <div className="qx-page-header" style={{ marginTop: 14 }}>
        <div>
          <div className="qx-page-title">{c.name}</div>
          <div className="qx-page-subtitle">
            {campaign.campaign_id} · v{campaign.config_version} · effective {new Date(campaign.config_effective_from).toLocaleString()}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <StatusBadge status={campaign.status} />
          <Link to={`/campaigns/${campaign.campaign_id}/edit`} className="qx-btn qx-btn-sm">
            Edit
          </Link>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 18, flexWrap: "wrap" }}>
        {campaign.status === "draft" && (
          <button className="qx-btn qx-btn-primary qx-btn-sm" disabled={busy} onClick={() => lifecycleAction("activate")}>
            Activate
          </button>
        )}
        {campaign.status === "active" && (
          <button className="qx-btn qx-btn-sm" disabled={busy} onClick={() => setPauseModalOpen(true)}>
            Pause
          </button>
        )}
        {campaign.status === "paused" && (
          <button className="qx-btn qx-btn-primary qx-btn-sm" disabled={busy} onClick={() => lifecycleAction("resume")}>
            Resume
          </button>
        )}
        {!["ended", "purged"].includes(campaign.status) && (
          <button className="qx-btn qx-btn-danger qx-btn-sm" disabled={busy} onClick={() => setConfirmEnd(true)}>
            End / Archive
          </button>
        )}
        {campaign.status === "ended" && (
          <button
            className="qx-btn qx-btn-danger-solid qx-btn-sm"
            disabled={busy}
            onClick={() => setPurgeOpen(true)}
            data-testid="purge-campaign-button"
          >
            Purge Campaign Data
          </button>
        )}
      </div>

      {campaign.status === "purged" && (
        <div className="qx-purge-warning" style={{ marginBottom: 18 }} data-testid="purged-banner">
          This campaign's operational data was permanently purged. A minimal tombstone remains for
          audit integrity; old tracking links no longer create clicks or attribution.
        </div>
      )}

      {campaign.status === "paused" && campaign.status_reason && (
        <div className="qx-foundation-note" style={{ marginBottom: 18 }}>
          Paused ({campaign.status_reason_type}): {campaign.status_reason}
        </div>
      )}

      <div className="qx-card" style={{ marginBottom: 20 }}>
        <div className="qx-row">
          <Field label="Advertiser" value={c.advertiser_name} />
          <Field label="Platform" value={c.platform} />
          <Field label="Postback platform" value={c.postback_platform} />
          <Field label="Payout range" value={c.payout_min != null || c.payout_max != null ? `₹${c.payout_min ?? "—"} – ₹${c.payout_max ?? "—"}` : "—"} />
          <Field label="Daily cap" value={c.daily_cap != null ? String(c.daily_cap) : "Unlimited"} />
          <Field label="Overall cap" value={c.overall_cap != null ? String(c.overall_cap) : "Unlimited"} />
          <Field label="Publisher access" value={c.approval_mode === "requires_approval" ? "Requires approval" : "Promote immediately"} />
          <Field label="Tracking time" value={c.tracking_window_hours ? `${c.tracking_window_hours} hours` : "None (earned at postback)"} />
        </div>
        {c.description && (
          <div style={{ marginTop: 12 }}>
            <div className="qx-kpi-label">Description</div>
            <div style={{ fontSize: 13 }}>{c.description}</div>
          </div>
        )}
      </div>

      <div className="qx-section-title" style={{ marginTop: 0 }}>Events</div>
      <div className="qx-table-wrap" style={{ marginBottom: 20 }}>
        <table className="qx-table">
          <thead>
            <tr><th>Event</th><th>Payout</th><th>Source</th></tr>
          </thead>
          <tbody>
            {c.events.map((ev, i) => (
              <tr key={i}>
                <td>{ev.event_name}</td>
                <td className={`qx-amount ${ev.payout > 0 ? "positive" : ""}`}>₹{ev.payout}</td>
                <td style={{ textTransform: "capitalize" }}>{ev.completion_source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="qx-section-title">Configuration history</div>
      <div className="qx-page-subtitle" style={{ marginBottom: 10 }}>
        Every edit is preserved as an immutable version — nothing here is ever overwritten.
      </div>
      <div className="qx-table-wrap">
        <table className="qx-table">
          <thead>
            <tr><th>Version</th><th>Name at the time</th><th>Applied scope</th><th>Effective from</th></tr>
          </thead>
          <tbody>
            {history.map((v) => (
              <tr key={v.version}>
                <td>v{v.version}</td>
                <td>{v.name}</td>
                <td style={{ textTransform: "capitalize" }}>{v.apply_scope.replace(/_/g, " ")}</td>
                <td>{new Date(v.effective_from).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pauseModalOpen && <PauseModal onCancel={() => setPauseModalOpen(false)} onConfirm={pause} busy={busy} />}

      {purgeOpen && (
        <PurgeModal
          campaignId={campaign.campaign_id}
          onClose={() => setPurgeOpen(false)}
          onPurged={load}
        />
      )}

      {confirmEnd && (
        <Modal title="End this campaign?" onClose={() => setConfirmEnd(false)}>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", margin: "8px 0 16px" }}>
            This stops new tracking traffic. Historical data remains fully accessible and is never deleted.
            This cannot be undone from here.
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button className="qx-btn" onClick={() => setConfirmEnd(false)}>Cancel</button>
            <button className="qx-btn qx-btn-danger" disabled={busy} onClick={() => lifecycleAction("end")}>
              End Campaign
            </button>
          </div>
        </Modal>
      )}
    </AppShell>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <div className="qx-kpi-label">{label}</div>
      <div>{value ?? "—"}</div>
    </div>
  );
}

function PauseModal({ onCancel, onConfirm, busy }: { onCancel: () => void; onConfirm: (reason: string) => void; busy: boolean }) {
  const [reason, setReason] = useState("");
  return (
    <Modal title="Pause campaign" onClose={onCancel}>
      <p style={{ fontSize: 13, color: "var(--text-secondary)", margin: "8px 0 12px" }}>
        A reason is required and is recorded in the audit log. New tracking traffic stops immediately;
        historical data is unaffected.
      </p>
      <div className="qx-field">
        <label htmlFor="pause-reason">Reason</label>
        <textarea id="pause-reason" className="qx-textarea" value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button className="qx-btn" onClick={onCancel}>Cancel</button>
        <button className="qx-btn qx-btn-primary" disabled={busy || !reason.trim()} onClick={() => onConfirm(reason)}>
          Pause Campaign
        </button>
      </div>
    </Modal>
  );
}

function PurgeModal({
  campaignId,
  onClose,
  onPurged,
}: {
  campaignId: string;
  onClose: () => void;
  onPurged: () => void;
}) {
  const [preview, setPreview] = useState<PurgePreview | null>(null);
  const [confirmName, setConfirmName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PurgeResult | null>(null);
  const [noticeOpen, setNoticeOpen] = useState(false);

  useEffect(() => {
    api
      .get<PurgePreview>(`/admin/campaigns/${campaignId}/purge-preview`)
      .then((r) => setPreview(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load purge preview"));
  }, [campaignId]);

  async function execute() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<PurgeResult>(`/admin/campaigns/${campaignId}/purge`, {
        confirm_campaign_name: confirmName,
      });
      setResult(r.data); setNoticeOpen(true);
      onPurged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Purge failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Purge Campaign Data" onClose={onClose}>
      <ErrorBanner message={error} />

      {result ? (
        <div data-testid="purge-result">
          <SuccessPopup open={noticeOpen} onClose={() => setNoticeOpen(false)} title="Campaign purged">
            Purge {result.status} — operation <strong>{result.purge_id}</strong>. {result.total_deleted} records deleted.
          </SuccessPopup>
          <div className="qx-table-wrap" style={{ marginBottom: 12 }}>
            <table className="qx-table">
              <thead>
                <tr><th>Category</th><th>Deleted</th><th>Remaining</th></tr>
              </thead>
              <tbody>
                {Object.entries(result.deleted_counts).map(([label, count]) => (
                  <tr key={label}>
                    <td>{label}</td>
                    <td>{count}</td>
                    <td>{result.verification.campaign_records_remaining[
                      { "Tracking Links": "tracking_links", "Campaign Access Records": "campaign_access", "Clicks": "clicks", "Conversions": "conversions", "Inbound Postback Logs": "inbound_postbacks", "Outbound Postback Logs": "outbound_postbacks", "Operational Events": "campaign_events", "Temporary Attribution Data": "attribution_mappings", "Postback Endpoints": "postback_endpoints", "Fraud/Operational Records": "blocked_ips" }[label] ?? ""
                    ] ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="qx-verification-list" data-testid="purge-verification">
            <li className={result.verification.all_purgeable_records_removed ? "ok" : "bad"}>
              {result.verification.all_purgeable_records_removed ? "✓" : "✗"} Selected campaign purgeable records: 0 remaining
            </li>
            <li className={result.verification.unrelated_totals_unchanged ? "ok" : "bad"}>
              {result.verification.unrelated_totals_unchanged ? "✓" : "✗"} Unrelated campaigns, publishers, managers and users: unchanged
            </li>
            <li className={result.verification.campaign_tombstone_present ? "ok" : "bad"}>
              {result.verification.campaign_tombstone_present ? "✓" : "✗"} Campaign tombstone retained for audit integrity
            </li>
            <li className={result.verification.audit_record_written ? "ok" : "bad"}>
              {result.verification.audit_record_written ? "✓" : "✗"} Immutable audit record written
            </li>
          </ul>
          <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 12 }}>{result.message}</p>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
            <button className="qx-btn qx-btn-primary" onClick={onClose} data-testid="purge-done-button">Done</button>
          </div>
        </div>
      ) : !preview ? (
        <div className="qx-empty-state">Loading preview…</div>
      ) : (
        <div data-testid="purge-preview">
          <div className="qx-card" style={{ marginBottom: 14, padding: 13 }}>
            <div className="qx-row">
              <div>
                <div className="qx-kpi-label">Campaign</div>
                <div style={{ fontWeight: 700 }} data-testid="purge-preview-name">{preview.campaign_name}</div>
              </div>
              <div>
                <div className="qx-kpi-label">Campaign ID</div>
                <div data-testid="purge-preview-id">{preview.campaign_id}</div>
              </div>
              <div>
                <div className="qx-kpi-label">Status</div>
                <StatusBadge status={preview.status} />
              </div>
            </div>
          </div>

          {!preview.eligible && (
            <div className="qx-purge-warning" style={{ marginBottom: 14 }} data-testid="purge-ineligible">
              {preview.eligibility_reason}
            </div>
          )}

          <div className="qx-kpi-label">Data that will be permanently deleted (actual database counts)</div>
          <div className="qx-table-wrap" style={{ margin: "8px 0 14px" }}>
            <table className="qx-table">
              <thead>
                <tr><th>Category</th><th>Records</th></tr>
              </thead>
              <tbody>
                {preview.categories.map((c) => (
                  <tr key={c.collection} data-testid={`purge-category-${c.collection}`}>
                    <td>{c.label}</td>
                    <td>{c.count}</td>
                  </tr>
                ))}
                <tr>
                  <td style={{ fontWeight: 800 }}>Total purgeable records</td>
                  <td style={{ fontWeight: 800 }} data-testid="purge-total">{preview.total_purgeable_records}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="qx-purge-warning" style={{ marginBottom: 14 }}>
            WARNING: This permanently deletes purgeable operational data belonging ONLY to this
            campaign. Publishers, managers, users, other campaigns, audit logs and financial records
            are never touched. This cannot be undone.
          </div>

          <div className="qx-field">
            <label htmlFor="purge-confirm-name">Type the exact campaign name to confirm: <strong>{preview.campaign_name}</strong></label>
            <input
              id="purge-confirm-name"
              className="qx-input"
              value={confirmName}
              onChange={(e) => setConfirmName(e.target.value)}
              autoComplete="off"
              data-testid="purge-confirm-input"
            />
          </div>

          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button className="qx-btn" onClick={onClose}>Cancel</button>
            <button
              className="qx-btn qx-btn-danger-solid"
              disabled={busy || !preview.eligible || confirmName !== preview.campaign_name}
              onClick={execute}
              data-testid="purge-confirm-button"
            >
              {busy ? "Purging…" : "Permanently Purge Campaign Data"}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
