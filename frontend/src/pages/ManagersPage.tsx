import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { buildInviteLink } from "../api/inviteLink";
import { AppShell } from "../components/AppShell";
import { EmptyState, ErrorBanner, Modal, Pagination, StatusBadge } from "../components/Common";

interface ManagerRow {
  user_id: string;
  email: string;
  account_status: string;
  email_verified: boolean;
  created_at: string;
}

const PAGE_SIZE = 20;

export function ManagersPage() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const q = params.get("q") ?? "";
  const page = parseInt(params.get("page") ?? "1", 10);

  const [rows, setRows] = useState<ManagerRow[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);

  function load() {
    api
      .get<ManagerRow[]>("/admin/managers", {
        status: status || undefined,
        q: q || undefined,
        page,
        page_size: PAGE_SIZE,
      })
      .then((r) => {
        setRows(r.data);
        setTotal(r.totalCount ?? r.data.length);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load managers"));
  }

  useEffect(load, [status, q, page]);

  async function act(userId: string, action: "approve" | "reject") {
    try {
      if (action === "reject") {
        const reason = window.prompt("Reason for rejecting this manager (optional):") ?? "";
        await api.post(`/admin/managers/${userId}/reject`, { reason: reason || null });
      } else {
        await api.post(`/admin/managers/${userId}/approve`);
      }
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    }
  }

  return (
    <AppShell title="Managers">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Manager Management</div>
          <div className="qx-page-subtitle">Onboard, review, and manage Affiliate Managers.</div>
        </div>
        <button className="qx-btn qx-btn-primary" onClick={() => setInviteOpen(true)}>
          + Add Manager
        </button>
      </div>

      <ErrorBanner message={error} />

      <div className="qx-row" style={{ marginBottom: 14 }}>
        <input
          className="qx-input"
          placeholder="Search by email…"
          defaultValue={q}
          onKeyDown={(e) => {
            if (e.key === "Enter") setParams({ status, q: e.currentTarget.value, page: "1" });
          }}
        />
        <select
          className="qx-select"
          value={status}
          onChange={(e) => setParams({ status: e.target.value, q, page: "1" })}
        >
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="active">Active</option>
          <option value="rejected">Rejected</option>
          <option value="suspended">Suspended</option>
          <option value="deactivated">Deactivated</option>
        </select>
      </div>

      {rows.length === 0 ? (
        <EmptyState message="No managers match these filters." />
      ) : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Status</th>
                <th>Email verified</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.user_id}>
                  <td>
                    <Link to={`/managers/${m.user_id}`}>{m.email}</Link>
                  </td>
                  <td><StatusBadge status={m.account_status} /></td>
                  <td>{m.email_verified ? "Yes" : "No"}</td>
                  <td>{new Date(m.created_at).toLocaleDateString()}</td>
                  <td>
                    {m.account_status === "pending" && (
                      <div className="qx-table-actions">
                        <button className="qx-btn qx-btn-sm qx-btn-primary" onClick={() => act(m.user_id, "approve")}>
                          Approve
                        </button>
                        <button className="qx-btn qx-btn-sm qx-btn-danger" onClick={() => act(m.user_id, "reject")}>
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

      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onChange={(p) => setParams({ status, q, page: String(p) })} />

      {inviteOpen && <InviteManagerModal onClose={() => setInviteOpen(false)} />}
    </AppShell>
  );
}

function InviteManagerModal({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [result, setResult] = useState<{ invite_token: string; expires_at: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const { data } = await api.post<{ invite_token: string; expires_at: string }>("/invites/manager", {
        target_email: email || null,
      });
      setResult(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to create invite");
    } finally {
      setSubmitting(false);
    }
  }

  const signupLink = result ? buildInviteLink(result.invite_token) : "";

  return (
    <Modal title="Add Manager" onClose={onClose}>
      <p style={{ fontSize: 12.5, color: "var(--text-secondary)", margin: "6px 0 14px" }}>
        Generates a secure, single-use invite link. The manager completes their own signup and email
        verification; you approve the application once it's submitted.
      </p>
      <ErrorBanner message={error} />
      {!result ? (
        <>
          <div className="qx-field">
            <label htmlFor="invite-email">Email (optional — leave blank for an open invite)</label>
            <input id="invite-email" className="qx-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <button className="qx-btn qx-btn-primary" disabled={submitting} onClick={submit}>
            {submitting ? "Generating…" : "Generate Invite"}
          </button>
        </>
      ) : (
        <>
          <div className="qx-field">
            <label>Signup link (shown once — copy it now)</label>
            <input className="qx-input" readOnly value={signupLink} onFocus={(e) => e.currentTarget.select()} />
          </div>
          <div className="qx-hint">Expires {new Date(result.expires_at).toLocaleString()}</div>
          <button className="qx-btn" style={{ marginTop: 12 }} onClick={onClose}>
            Done
          </button>
        </>
      )}
    </Modal>
  );
}
