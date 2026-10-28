import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { EmptyState, ErrorBanner } from "../components/Common";
import { SuccessPopup } from "../components/SuccessPopup";
import { useAuth } from "../auth/AuthContext";

interface Announcement { id: string; title: string; message: string; audience: "all" | "managers" | "publishers"; created_at: string }

const AUD_LABEL: Record<string, string> = { all: "Everyone", managers: "Managers", publishers: "Publishers" };
export const SEEN_KEY = "qx_seen_announcement";

/** Messages from the Super Admin. Managers and Publishers read them here; the Super Admin writes and removes them. */
export function NotificationsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "super_admin";
  const [items, setItems] = useState<Announcement[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [audience, setAudience] = useState<Announcement["audience"]>("all");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  function load() {
    api.get<{ items: Announcement[] }>("/announcements")
      .then((r) => {
        setItems(r.data.items);
        try { if (r.data.items[0]) localStorage.setItem(SEEN_KEY, r.data.items[0].id); } catch { /* storage unavailable */ }
        window.dispatchEvent(new Event("qx-announcements-seen"));
      })
      .catch((e) => { setItems([]); setError(e instanceof ApiError ? e.message : "Failed to load messages"); });
  }
  useEffect(load, []);

  async function send() {
    if (!title.trim() || !message.trim()) return;
    setBusy(true); setError(null);
    try {
      await api.post("/announcements", { title, message, audience });
      setTitle(""); setMessage(""); setSent(true); load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not send the message");
    } finally { setBusy(false); }
  }

  async function remove(id: string) {
    setError(null);
    try { await api.delete(`/announcements/${id}`); load(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Could not remove the message"); }
  }

  return (
    <AppShell title="Notifications">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Notifications</div>
          <div className="qx-page-subtitle">
            {isAdmin ? "Messages you send here appear on every Manager and Publisher Notifications page until you remove them."
              : "Messages from the DigiSanchaar team."}
          </div>
        </div>
      </div>
      <ErrorBanner message={error} />

      {isAdmin && (
        <div className="qx-card" style={{ marginBottom: 18 }}>
          <div className="qx-field">
            <label htmlFor="an-title">Title</label>
            <input id="an-title" className="qx-input" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. New campaign live" />
          </div>
          <div className="qx-field">
            <label htmlFor="an-msg">Message</label>
            <textarea id="an-msg" className="qx-textarea" maxLength={2000} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Write the message…" />
          </div>
          <div className="qx-field">
            <label htmlFor="an-aud">Send to</label>
            <select id="an-aud" className="qx-select" value={audience} onChange={(e) => setAudience(e.target.value as Announcement["audience"])}>
              <option value="all">Managers and Publishers</option>
              <option value="managers">Managers only</option>
              <option value="publishers">Publishers only</option>
            </select>
          </div>
          <button className="qx-btn qx-btn-primary" disabled={busy || !title.trim() || !message.trim()} onClick={send}>{busy ? "Sending…" : "Send message"}</button>
        </div>
      )}

      {items === null ? <div className="qx-hint">Loading…</div> : items.length === 0 ? <EmptyState message="No messages." /> : (
        <div style={{ display: "grid", gap: 12 }}>
          {items.map((a) => (
            <div key={a.id} className="qx-card" data-testid="announcement">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                <div style={{ fontWeight: 700, fontSize: 16, minWidth: 0, overflowWrap: "anywhere" }}>{a.title}</div>
                {isAdmin && <button className="qx-btn qx-btn-sm qx-btn-danger" onClick={() => remove(a.id)}>Remove</button>}
              </div>
              <div style={{ margin: "8px 0", whiteSpace: "pre-wrap", overflowWrap: "anywhere", color: "var(--text-secondary)" }}>{a.message}</div>
              <div className="qx-hint">
                {new Date(a.created_at).toLocaleString()}{isAdmin ? ` · To: ${AUD_LABEL[a.audience] ?? a.audience}` : ""}
              </div>
            </div>
          ))}
        </div>
      )}
      <SuccessPopup open={sent} onClose={() => setSent(false)} title="Message sent">It now shows on the Notifications page of the selected users.</SuccessPopup>
    </AppShell>
  );
}
