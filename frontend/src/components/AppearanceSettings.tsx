import { useState } from "react";
import { api, ApiError } from "../api/client";
import { ACCENT_OPTIONS, DEFAULT_ACCENT, isAccentId, useAccent, type AccentId } from "../theme/AccentContext";
import { SuccessPopup } from "./SuccessPopup";

/** Super Admin only (rendered inside the Super Admin Settings page). */
export function AppearanceSettings() {
  const { accent, applyAccent } = useAccent();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function choose(next: AccentId) {
    if (busy || next === accent) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const r = await api.put<{ accent_theme: string }>("/admin/settings/appearance", { accent_theme: next });
      if (isAccentId(r.data?.accent_theme)) applyAccent(r.data.accent_theme);
      setSaved(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save the accent theme");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="qx-section-title">Appearance</div>
      <div className="qx-card" style={{ marginBottom: 20 }} data-testid="appearance-card">
        <div style={{ fontWeight: 700, fontSize: 15 }}>Global Accent Theme</div>
        <div className="qx-hint" style={{ marginTop: 4 }}>
          Controls the primary accent colour across the DigiSanchaar platform. Everyone keeps their own
          Light / Dark mode.
        </div>

        {error && <div className="qx-error-banner" role="alert" style={{ marginTop: 12 }}>{error}</div>}
        <SuccessPopup open={saved && !error} onClose={() => setSaved(false)} title="Appearance saved" testId="appearance-saved">
          Accent theme updated for all roles.
        </SuccessPopup>

        <div className="qx-accent-grid" role="radiogroup" aria-label="Global accent theme">
          {ACCENT_OPTIONS.map((o) => {
            const selected = o.id === accent;
            return (
              <button
                key={o.id}
                type="button"
                role="radio"
                aria-checked={selected}
                className="qx-accent-card"
                disabled={busy}
                onClick={() => choose(o.id)}
                data-testid={`accent-${o.id}`}
              >
                <span className="qx-accent-swatch" style={{ background: o.swatch }} aria-hidden="true" />
                <span className="qx-accent-name">{o.label}</span>
                {o.id === DEFAULT_ACCENT && <span className="qx-accent-default">Default</span>}
                {selected && <span className="qx-accent-check" aria-hidden="true">✓</span>}
                {selected && <span className="qx-sr-only">Selected</span>}
              </button>
            );
          })}
        </div>

        <div className="qx-kpi-label" style={{ marginBottom: 8 }}>Preview</div>
        <div className="qx-accent-preview" aria-hidden="true">
          <span className="qx-btn qx-btn-primary">Primary button</span>
          <span className="qx-btn qx-btn-outline" style={{ height: 42 }}>Secondary</span>
          <span className="qx-tab active">Active tab</span>
          <span className="qx-tab">Tab</span>
          <span className="qx-nav-link active" style={{ width: "auto", display: "inline-flex", paddingRight: 30 }}>Active navigation</span>
          <span style={{ color: "var(--accent-primary-text)", fontWeight: 700, fontSize: 13.5 }}>Accent link</span>
        </div>
      </div>
    </>
  );
}
