import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { AppearanceSettings } from "../components/AppearanceSettings";
import { CommunitySettings } from "../components/CommunitySettings";
import { ErrorBanner, FoundationNote } from "../components/Common";
import { SuccessPopup } from "../components/SuccessPopup";

interface TrackingDomainConfig {
  configured: boolean;
  tracking_base_url: string | null;
  status: string;
  verified: boolean;
  verified_at: string | null;
  verification_note: string;
  effective_source: string | null;
  example_url: string | null;
  created_at: string | null;
  updated_at: string | null;
  updated_by: string | null;
}

export function SettingsPage() {
  const [config, setConfig] = useState<TrackingDomainConfig | null>(null);
  const [url, setUrl] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function load() {
    api
      .get<TrackingDomainConfig>("/admin/settings/tracking-domain")
      .then((r) => {
        setConfig(r.data);
        setUrl(r.data.tracking_base_url ?? "");
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load settings"));
  }

  useEffect(load, []);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const r = await api.put<TrackingDomainConfig>("/admin/settings/tracking-domain", {
        tracking_base_url: url,
        reason: reason || undefined,
      });
      setConfig(r.data);
      setSaved(true);
      setReason("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save tracking domain");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell title="System Settings">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">System Settings</div>
          <div className="qx-page-subtitle">Network-wide configuration. Every change is audited.</div>
        </div>
      </div>

      <ErrorBanner message={error} />
      <SuccessPopup open={saved} onClose={() => setSaved(false)} title="Tracking domain updated" testId="tracking-domain-saved">
        New tracking links will use the new domain. Historical clicks, conversions, attribution and earnings are never rewritten.
      </SuccessPopup>

      <div className="qx-section-title" style={{ marginTop: 0 }}>Domain &amp; Tracking</div>
      <div className="qx-card" data-testid="tracking-domain-card" style={{ marginBottom: 20 }}>
        {!config ? (
          <div className="qx-empty-state">Loading…</div>
        ) : (
          <>
            <div className="qx-row" style={{ marginBottom: 14 }}>
              <div>
                <div className="qx-kpi-label">Active tracking base URL</div>
                <div data-testid="tracking-domain-current" style={{ fontWeight: 700, fontSize: 14 }}>
                  {config.tracking_base_url ?? "Not configured"}
                </div>
              </div>
              <div>
                <div className="qx-kpi-label">Source</div>
                <div style={{ textTransform: "capitalize" }}>{config.effective_source ?? "—"}</div>
              </div>
              <div>
                <div className="qx-kpi-label">Status</div>
                <div data-testid="tracking-domain-status">
                  {config.configured ? "Active" : "Not configured"}
                  {config.configured && !config.verified && " · Unverified"}
                </div>
              </div>
              <div>
                <div className="qx-kpi-label">Last updated</div>
                <div>{config.updated_at ? new Date(config.updated_at).toLocaleString() : "—"}</div>
              </div>
            </div>

            {config.configured && (
              <div className="qx-callout" style={{ marginBottom: 14 }} data-testid="tracking-domain-verification-note">
                <div className="qx-callout-title">Verification</div>
                {config.verification_note}
              </div>
            )}

            {config.example_url && (
              <div style={{ marginBottom: 16 }}>
                <div className="qx-kpi-label">Canonical link format (generated server-side)</div>
                <code className="qx-code" data-testid="tracking-domain-example">{config.example_url}</code>
              </div>
            )}

            <form onSubmit={save}>
              <div className="qx-field">
                <label htmlFor="tracking-base-url">Tracking base URL</label>
                <input
                  id="tracking-base-url"
                  className="qx-input"
                  placeholder="https://track.example.com"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  data-testid="tracking-domain-input"
                />
                <div className="qx-hint">
                  Absolute URL, HTTPS in production, no credentials, no query string, no fragment.
                  Public links are short: {"{domain}/{campaign-code}/{link-code}"}.
                </div>
              </div>
              <div className="qx-field">
                <label htmlFor="tracking-domain-reason">Reason (recorded in audit log)</label>
                <input
                  id="tracking-domain-reason"
                  className="qx-input"
                  placeholder="e.g. Migrating tracking to dedicated domain"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  data-testid="tracking-domain-reason-input"
                />
              </div>
              <button className="qx-btn qx-btn-primary" disabled={busy || !url.trim()} type="submit" data-testid="tracking-domain-save-button">
                {busy ? "Saving…" : "Save Tracking Domain"}
              </button>
            </form>
          </>
        )}
      </div>

      <CommunitySettings />

      <AppearanceSettings />

      <FoundationNote>
        Additional settings sections appear here when their modules are enabled. Secrets — JWT keys, database credentials, SMTP passwords —
        are never exposed through this UI.
      </FoundationNote>
    </AppShell>
  );
}
