import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ErrorBanner } from "../components/Common";
import { CampaignForm, EMPTY_CAMPAIGN_FORM, toApiPayload, type CampaignFormValues } from "./CampaignForm";

export function CampaignCreatePage() {
  const navigate = useNavigate();
  const [value, setValue] = useState<CampaignFormValues>(EMPTY_CAMPAIGN_FORM);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const { data } = await api.post<{ campaign_id: string }>("/admin/campaigns", toApiPayload(value));
      navigate(`/campaigns/${data.campaign_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to create campaign");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell title="Create Campaign">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Create Campaign</div>
          <div className="qx-page-subtitle">Starts in Draft — activate it once you're ready to go live.</div>
        </div>
      </div>
      <ErrorBanner message={error} />
      <div className="qx-card" style={{ maxWidth: 760 }}>
        <CampaignForm value={value} onChange={setValue} />
        <div style={{ marginTop: 18, display: "flex", gap: 10 }}>
          <button className="qx-btn qx-btn-primary" disabled={submitting || !value.name.trim()} onClick={submit}>
            {submitting ? "Creating…" : "Create Campaign"}
          </button>
        </div>
      </div>
    </AppShell>
  );
}
