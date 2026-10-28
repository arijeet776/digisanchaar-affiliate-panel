import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../../api/client";
import { buildInviteLink } from "../../api/inviteLink";
import { AppShell } from "../../components/AppShell";
import { ErrorBanner, Modal, StatusBadge } from "../../components/Common";
import { SuccessPopup } from "../../components/SuccessPopup";

interface PublisherRow {
  user_id: string;
  publisher_id: string;
  manager_id: string | null;
  display_name: string;
  email: string;
  account_status: string;
  mobile?: string | null;
  company?: string | null;
  created_at?: string | null;
}

interface InviteResult {
  invite_token: string;
  target_email: string | null;
  expires_at: string;
}

export function ManagerPublishersPage() {
  const [publishers, setPublishers] = useState<PublisherRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  function load() {
    api
      .get<PublisherRow[]>("/publishers")
      .then((r) => setPublishers(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load publishers"));
  }

  useEffect(load, []);

  async function act(userId: string, action: "approve" | "reject") {
    setBusyId(userId);
    setError(null);
    try {
      await api.post(`/publishers/${userId}/${action}`, action === "reject" ? { reason: "Rejected by manager" } : {});
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `Failed to ${action} publisher`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <AppShell title="My Publishers">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">My Publishers</div>
          <div className="qx-page-subtitle">Publishers assigned to you. You can invite, approve, or reject within your scope only.</div>
        </div>
        <button className="qx-btn qx-btn-primary" onClick={() => setInviteOpen(true)} data-testid="manager-invite-publisher-button">
          + Invite Publisher
        </button>
      </div>

      <ErrorBanner message={error} />

      {!publishers ? (
        <div className="qx-empty-state">Loading…</div>
      ) : publishers.length === 0 ? (
        <div className="qx-empty-state" data-testid="manager-publishers-empty">
          No publishers yet. Invite your first publisher to get started.
        </div>
      ) : (
        <div className="qx-table-wrap" data-testid="manager-publishers-table">
          <table className="qx-table">
            <thead>
              <tr>
                <th>Publisher ID</th>
                <th>Name</th>
                <th>Email</th>
                <th>Mobile</th>
                <th>Company</th>
                <th>Status</th>
                <th>Submitted</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {publishers.map((p) => (
                <tr key={p.user_id}>
                  <td>{p.publisher_id}</td>
                  <td>{p.display_name}</td>
                  <td>{p.email}</td>
                  <td>{p.mobile ?? "—"}</td>
                  <td>{p.company ?? "—"}</td>
                  <td><StatusBadge status={p.account_status} /></td>
                  <td>{p.created_at ? new Date(p.created_at).toLocaleDateString() : "—"}</td>
                  <td>
                    {p.account_status === "pending" && (
                      <div className="qx-table-actions">
                        <button className="qx-btn qx-btn-sm qx-btn-primary" disabled={busyId === p.user_id} onClick={() => act(p.user_id, "approve")} data-testid={`approve-${p.publisher_id}`}>
                          Approve
                        </button>
                        <button className="qx-btn qx-btn-sm qx-btn-danger" disabled={busyId === p.user_id} onClick={() => act(p.user_id, "reject")} data-testid={`reject-${p.publisher_id}`}>
                          Reject
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {inviteOpen && <InvitePublisherModal onClose={() => setInviteOpen(false)} />}
    </AppShell>
  );
}

function InvitePublisherModal({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invite, setInvite] = useState<InviteResult | null>(null);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<InviteResult>("/invites/publisher", { target_email: email || null });
      setInvite(r.data); setNoticeOpen(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create invite");
    } finally {
      setBusy(false);
    }
  }

  const inviteUrl = invite ? buildInviteLink(invite.invite_token) : null;

  return (
    <Modal title="Invite Publisher" onClose={onClose}>
      <ErrorBanner message={error} />
      {!invite ? (
        <form onSubmit={submit}>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", margin: "6px 0 14px" }}>
            Creates a single-use link that expires automatically. Publishers who register through it are assigned to you.
          </p>
          <div className="qx-field">
            <label htmlFor="invite-email">Publisher email</label>
            <input
              id="invite-email"
              className="qx-input"
              type="email"
              placeholder="publisher@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              data-testid="invite-email-input"
            />
            <div className="qx-hint">Only this email can claim the invite.</div>
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button className="qx-btn" onClick={onClose} type="button">Cancel</button>
            <button className="qx-btn qx-btn-primary" disabled={busy || !email.trim()} type="submit" data-testid="invite-create-button">
              {busy ? "Creating…" : "Create Invite"}
            </button>
          </div>
        </form>
      ) : (
        <div data-testid="invite-created">
          <SuccessPopup open={noticeOpen} onClose={() => setNoticeOpen(false)} title="Invite created">
            Invite created for {invite.target_email}.
          </SuccessPopup>
          <div className="qx-field">
            <label>Invite link (share with the publisher)</label>
            <code className="qx-code" data-testid="invite-link">{inviteUrl}</code>
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button
              className="qx-btn qx-btn-primary"
              data-testid="invite-copy-button"
              onClick={async () => {
                if (inviteUrl) {
                  await navigator.clipboard.writeText(inviteUrl);
                  setCopied(true);
                }
              }}
            >
              {copied ? "Copied ✓" : "Copy Link"}
            </button>
            <button className="qx-btn" onClick={onClose}>Done</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
