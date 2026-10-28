import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import { SuccessPopup } from "./SuccessPopup";

/** Super Admin only: Support / Community -> DigiSanchaar WhatsApp Group Link. */
export function CommunitySettings() {
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  useEffect(() => {
    api.get<{ whatsapp_group_link: string | null }>("/admin/settings/support")
      .then((r) => { setValue(r.data.whatsapp_group_link ?? ""); setSaved(r.data.whatsapp_group_link); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load"));
  }, []);

  async function save(e: FormEvent, clear = false) {
    e.preventDefault();
    setBusy(true); setError(null); setOk(null);
    try {
      const r = await api.put<{ whatsapp_group_link: string | null }>("/admin/settings/support", { whatsapp_group_link: clear ? "" : value.trim() });
      setSaved(r.data.whatsapp_group_link); setValue(r.data.whatsapp_group_link ?? "");
      setOk(r.data.whatsapp_group_link ? "WhatsApp group link saved." : "WhatsApp group link cleared.");
    } catch (err) { setError(err instanceof ApiError ? err.message : "Failed to save"); }
    finally { setBusy(false); }
  }

  return (
    <>
      <div className="qx-section-title">Support / Community</div>
      <form className="qx-card" style={{ marginBottom: 20 }} onSubmit={(e) => save(e)} data-testid="community-card">
        <div style={{ fontWeight: 700, fontSize: 15 }}>DigiSanchaar WhatsApp Group Link</div>
        <div className="qx-hint" style={{ marginTop: 4 }}>Shown to Publishers in Support &amp; Help as “Join DigiSanchaar WhatsApp Group”. Leave empty to hide it.</div>
        {error && <div className="qx-error-banner" role="alert" style={{ marginTop: 12 }}>{error}</div>}
        <SuccessPopup open={!!ok && !error} onClose={() => setOk(null)} title="Saved" testId="community-saved">{ok}</SuccessPopup>
        <div className="qx-field" style={{ marginTop: 14 }}>
          <label htmlFor="wa-link">Group invite link</label>
          <input id="wa-link" className="qx-input" type="url" inputMode="url" placeholder="https://chat.whatsapp.com/…" value={value}
            onChange={(e) => setValue(e.target.value)} data-testid="whatsapp-link-input" />
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button className="qx-btn qx-btn-primary" type="submit" disabled={busy} data-testid="whatsapp-link-save">{busy ? "Saving…" : "Save"}</button>
          {saved && <button className="qx-btn" type="button" disabled={busy} onClick={(e) => save(e, true)} data-testid="whatsapp-link-clear">Remove link</button>}
        </div>
      </form>
    </>
  );
}
