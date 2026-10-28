import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ErrorBanner } from "../components/Common";
import { CampaignForm, toApiPayload, type CampaignFormValues } from "./CampaignForm";

interface CampaignDetail {
  campaign_id: string;
  config: {
    name: string;
    advertiser_name: string | null;
    advertiser_tracking_url: string | null;
    logo_url: string | null;
    description: string | null;
    platform: string | null;
    postback_platform: "trackier" | "trackix" | "offer18" | "custom";
    click_id_param?: string | null; advertiser_click_id_param?: string | null;
    event_param?: string | null; campaign_title_param?: string | null; extra_click_id_params?: string[] | null;
    postback_config: Record<string, string>;
    payout_min: number | null;
    payout_max: number | null;
    daily_cap: number | null;
    overall_cap: number | null;
    approval_mode?: "promote_immediately" | "requires_approval";
    category?: string | null; kind?: "standard" | "shopping" | "survey"; tracking_only?: boolean; countries?: string[];
    tracking_window_hours?: number | null;
    events: { event_name: string; payout: number; completion_source: "online" | "offline" }[];
  };
}

type ApplyScope = "future_only" | "existing_and_future";

export function CampaignEditPage() {
  const { campaignId = "" } = useParams();
  const navigate = useNavigate();
  const [value, setValue] = useState<CampaignFormValues | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [scopeDialogOpen, setScopeDialogOpen] = useState(false);
  const [selectedScope, setSelectedScope] = useState<ApplyScope>("future_only");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api
      .get<CampaignDetail>(`/admin/campaigns/${campaignId}`)
      .then((r) => {
        const c = r.data.config;
        setValue({
          name: c.name,
          advertiser_name: c.advertiser_name ?? "",
          advertiser_tracking_url: c.advertiser_tracking_url ?? "",
          logo_url: c.logo_url ?? "",
          description: c.description ?? "",
          postback_platform: c.postback_platform === "trackix" ? "custom" : c.postback_platform,
          click_id_param: c.click_id_param ?? "",
          advertiser_click_id_param: c.advertiser_click_id_param ?? "",
          event_param: c.event_param ?? "",
          campaign_title_param: c.campaign_title_param ?? "",
          extra_click_id_params: (c.extra_click_id_params ?? []).join(", "),
          payout_min: c.payout_min != null ? String(c.payout_min) : "",
          payout_max: c.payout_max != null ? String(c.payout_max) : "",
          daily_cap: c.daily_cap != null ? String(c.daily_cap) : "",
          overall_cap: c.overall_cap != null ? String(c.overall_cap) : "",
          approval_mode: c.approval_mode ?? "promote_immediately",
          category: c.category ?? "",
          kind: c.kind ?? "standard",
          tracking_only: !!c.tracking_only,
          countries: (c.countries ?? []).join(", "),
          tracking_window_hours: c.tracking_window_hours != null ? String(c.tracking_window_hours) : "",
          events: c.events,
        });
      })
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : "Failed to load campaign"));
  }, [campaignId]);

  async function saveWithScope(scope: ApplyScope) {
    if (!value) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.patch(`/admin/campaigns/${campaignId}`, { ...toApiPayload(value), apply_scope: scope });
      navigate(`/campaigns/${campaignId}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save campaign");
      setScopeDialogOpen(false);
    } finally {
      setSubmitting(false);
    }
  }

  if (loadError) {
    return (
      <AppShell title="Edit Campaign">
        <ErrorBanner message={loadError} />
      </AppShell>
    );
  }

  if (!value) {
    return (
      <AppShell title="Edit Campaign">
        <div className="qx-empty-state">Loading…</div>
      </AppShell>
    );
  }

  return (
    <AppShell title="Edit Campaign">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Edit Campaign</div>
          <div className="qx-page-subtitle">Every change is saved as a new, permanent configuration version — nothing is overwritten.</div>
        </div>
      </div>
      <ErrorBanner message={error} />
      <div className="qx-card" style={{ maxWidth: 760 }}>
        <CampaignForm value={value} onChange={setValue} />
        <div style={{ marginTop: 18 }}>
          <button className="qx-btn qx-btn-primary" disabled={!value.name.trim()} onClick={() => setScopeDialogOpen(true)}>
            Review &amp; Save Changes
          </button>
        </div>
      </div>

      {scopeDialogOpen && (
        <div className="qx-modal-backdrop" onClick={() => !submitting && setScopeDialogOpen(false)}>
          <div className="qx-modal" onClick={(e) => e.stopPropagation()}>
            <div className="qx-modal-title">Apply changes to?</div>
            <p style={{ fontSize: 12.5, color: "var(--text-secondary)", margin: "6px 0 16px" }}>
              The system never silently modifies historical records. Choose explicitly.
            </p>

            <div
              className={`qx-scope-option ${selectedScope === "future_only" ? "selected" : ""}`}
              onClick={() => setSelectedScope("future_only")}
            >
              <input type="radio" checked={selectedScope === "future_only"} onChange={() => setSelectedScope("future_only")} style={{ marginTop: 3 }} />
              <div>
                <div className="qx-scope-option-title">Future Leads Only</div>
                <div className="qx-scope-option-desc">
                  New configuration applies to leads created after this change. Historical records remain unchanged.
                </div>
              </div>
            </div>

            <div
              className={`qx-scope-option ${selectedScope === "existing_and_future" ? "selected" : ""}`}
              onClick={() => setSelectedScope("existing_and_future")}
            >
              <input type="radio" checked={selectedScope === "existing_and_future"} onChange={() => setSelectedScope("existing_and_future")} style={{ marginTop: 3 }} />
              <div>
                <div className="qx-scope-option-title">Existing + Future Leads</div>
                <div className="qx-scope-option-desc">
                  Apply this configuration to existing applicable records and future leads. This action is recorded in the audit log.
                </div>
              </div>
            </div>

            {selectedScope === "existing_and_future" && (
              <div className="qx-foundation-note" style={{ marginTop: 4, marginBottom: 14 }}>
                Your choice is recorded and applied by the tracking system. If no click or
                conversion records exist yet, there is nothing to apply retroactively.
              </div>
            )}

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}>
              <button className="qx-btn" disabled={submitting} onClick={() => setScopeDialogOpen(false)}>
                Cancel
              </button>
              <button className="qx-btn qx-btn-primary" disabled={submitting} onClick={() => saveWithScope(selectedScope)}>
                {submitting ? "Saving…" : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
