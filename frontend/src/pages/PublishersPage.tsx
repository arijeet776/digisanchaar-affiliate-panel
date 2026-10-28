import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { buildInviteLink } from "../api/inviteLink";
import { AppShell } from "../components/AppShell";
import { EmptyState, ErrorBanner, Modal, Pagination, StatusBadge } from "../components/Common";

interface PublisherRow {
  user_id: string;
  publisher_id: string;
  manager_id: string | null;
  manager_name: string | null;
  display_name: string;
  email: string;
  account_status: string;
  mobile: string | null;
  company: string | null;
  invitation_type: string | null;
  created_at: string | null;
}

interface AssignableManager {
  manager_id: string;
  display_name: string;
  email: string;
}

const sourceLabel = (t: string | null) =>
  t === "OPEN_REGISTRATION" ? "Public registration" : t === "SUPER_ADMIN_INVITE" ? "Super Admin invite" : t === "MANAGER_INVITE" ? "Manager invite" : "—";

const PAGE_SIZE = 20;

export function PublishersPage() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const managerId = params.get("manager_id") ?? "";
  const q = params.get("q") ?? "";
  const unassigned = params.get("unassigned") === "true";
  const page = parseInt(params.get("page") ?? "1", 10);

  const [rows, setRows] = useState<PublisherRow[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [assignFor, setAssignFor] = useState<{ row: PublisherRow; mode: "approve" | "assign" } | null>(null);
  const [rejectFor, setRejectFor] = useState<PublisherRow | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    api
      .get<PublisherRow[]>("/publishers", {
        status: status || undefined,
        manager_id: managerId || undefined,
        unassigned: unassigned || undefined,
        q: q || undefined,
        page,
        page_size: PAGE_SIZE,
      })
      .then((r) => {
        setRows(r.data);
        setTotal(r.totalCount ?? r.data.length);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load publishers"));
  }

  useEffect(load, [status, managerId, q, page, unassigned]);

  async function approve(row: PublisherRow, managerIdToAssign?: string) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/publishers/${row.user_id}/approve`, managerIdToAssign ? { manager_id: managerIdToAssign } : undefined);
      setAssignFor(null);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Approval failed");
      setAssignFor(null);
    } finally {
      setBusy(false);
    }
  }

  async function assignLater(row: PublisherRow, managerIdToAssign: string) {
    setBusy(true);
    setError(null);
    try {
      await api.put(`/publishers/${row.user_id}/manager`, { manager_id: managerIdToAssign });
      setAssignFor(null);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Assignment failed");
      setAssignFor(null);
    } finally {
      setBusy(false);
    }
  }

  async function reject(row: PublisherRow, reason: string) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/publishers/${row.user_id}/reject`, { reason: reason || null });
      setRejectFor(null);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Rejection failed");
      setRejectFor(null);
    } finally {
      setBusy(false);
    }
  }

  function next(patch: Record<string, string>, keepPage = false): Record<string, string> {
    const merged: Record<string, string> = { status, manager_id: managerId, q, ...(unassigned ? { unassigned: "true" } : {}), ...patch };
    if (!keepPage) merged.page = "1";
    return Object.fromEntries(Object.entries(merged).filter(([, v]) => v !== ""));
  }

  return (
    <AppShell title="Publishers">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Publisher Management</div>
          <div className="qx-page-subtitle">Review publisher applications and manage every publisher's Manager assignment.</div>
        </div>
        <button className="qx-btn qx-btn-primary" onClick={() => setInviteOpen(true)}>
          + Invite Publisher
        </button>
      </div>

      <ErrorBanner message={error} />

      <div className="qx-row" style={{ marginBottom: 14 }}>
        <input
          className="qx-input"
          placeholder="Search by name, email, publisher ID…"
          defaultValue={q}
          onKeyDown={(e) => {
            if (e.key === "Enter") setParams(next({ q: e.currentTarget.value }));
          }}
        />
        <select className="qx-select" value={status} onChange={(e) => setParams(next({ status: e.target.value }))}>
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="active">Active</option>
          <option value="rejected">Rejected</option>
          <option value="suspended">Suspended</option>
          <option value="deactivated">Deactivated</option>
        </select>
        <select
          className="qx-select"
          aria-label="Manager assignment"
          value={unassigned ? "unassigned" : ""}
          onChange={(e) => setParams(next({ unassigned: e.target.value === "unassigned" ? "true" : "" }))}
        >
          <option value="">All assignments</option>
          <option value="unassigned">Not assigned to a Manager</option>
        </select>
        <input
          className="qx-input"
          placeholder="Filter by Manager ID…"
          defaultValue={managerId}
          onKeyDown={(e) => {
            if (e.key === "Enter") setParams(next({ manager_id: e.currentTarget.value }));
          }}
        />
      </div>

      {rows.length === 0 ? (
        <EmptyState message="No publishers match these filters." />
      ) : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead>
              <tr>
                <th>Publisher</th>
                <th>Mobile</th>
                <th>Company</th>
                <th>Invited by</th>
                <th>Manager</th>
                <th>Status</th>
                <th>Submitted</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.user_id}>
                  <td>
                    <div className="qx-person">
                      <Link to={`/publishers/${p.user_id}`}><b>{p.display_name}</b></Link>
                      <span className="qx-cell-sub">{p.email} · ID {p.publisher_id}</span>
                    </div>
                  </td>
                  <td>{p.mobile ?? "—"}</td>
                  <td>{p.company ?? "—"}</td>
                  <td><span className="qx-source-pill">{sourceLabel(p.invitation_type)}</span></td>
                  <td>
                    {p.manager_id ? (
                      <div className="qx-person"><span>{p.manager_name ?? p.manager_id}</span><span className="qx-cell-sub">{p.manager_id}</span></div>
                    ) : (
                      <span className="qx-unassigned">Not Assigned</span>
                    )}
                  </td>
                  <td><StatusBadge status={p.account_status} /></td>
                  <td>{p.created_at ? new Date(p.created_at).toLocaleDateString() : "—"}</td>
                  <td>
                    {p.account_status === "pending" && (
                      <div className="qx-table-actions">
                        <button className="qx-btn qx-btn-sm qx-btn-primary" disabled={busy} onClick={() => approve(p)} data-testid={`approve-${p.publisher_id}`}>
                          Approve
                        </button>
                        {!p.manager_id && (
                          <button className="qx-btn qx-btn-sm" disabled={busy} onClick={() => setAssignFor({ row: p, mode: "approve" })} data-testid={`approve-assign-${p.publisher_id}`}>
                            Approve &amp; Assign Manager
                          </button>
                        )}
                        <button className="qx-btn qx-btn-sm qx-btn-danger" disabled={busy} onClick={() => setRejectFor(p)} data-testid={`reject-${p.publisher_id}`}>
                          Reject
                        </button>
                      </div>
                    )}
                    {p.account_status !== "pending" && p.account_status !== "rejected" && (
                      <div className="qx-table-actions">
                        <button className="qx-btn qx-btn-sm" disabled={busy} onClick={() => setAssignFor({ row: p, mode: "assign" })} data-testid={`assign-${p.publisher_id}`}>
                          {p.manager_id ? "Change Manager" : "Assign Manager"}
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

      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onChange={(p) => setParams(next({ page: String(p) }, true))} />

      {inviteOpen && <InvitePublisherModal onClose={() => setInviteOpen(false)} />}
      {assignFor && (
        <AssignManagerModal row={assignFor.row} mode={assignFor.mode} busy={busy} onClose={() => setAssignFor(null)}
          onConfirm={(mid) => (assignFor.mode === "approve" ? approve(assignFor.row, mid) : assignLater(assignFor.row, mid))} />
      )}
      {rejectFor && <RejectModal row={rejectFor} busy={busy} onClose={() => setRejectFor(null)} onConfirm={(reason) => reject(rejectFor, reason)} />}
    </AppShell>
  );
}

function AssignManagerModal({ row, mode, busy, onClose, onConfirm }: { row: PublisherRow; mode: "approve" | "assign"; busy: boolean; onClose: () => void; onConfirm: (managerId: string) => void }) {
  const [managers, setManagers] = useState<AssignableManager[] | null>(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AssignableManager[]>("/admin/managers/assignable")
      .then((r) => setManagers(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load managers"));
  }, []);

  return (
    <Modal title={mode === "approve" ? "Approve & Assign Manager" : row.manager_id ? "Change Manager" : "Assign Manager"} onClose={onClose}>
      <p className="qx-assign-hint">
        {mode === "approve"
          ? <>Approve <b>{row.display_name}</b> and assign the Manager who will look after this publisher. Only active Managers are listed. (Use plain Approve to skip this — you can assign a Manager later.)</>
          : <>Choose the Manager for <b>{row.display_name}</b>. Only active Managers are listed. Earlier activity keeps its original Manager.</>}
      </p>
      <ErrorBanner message={error} />
      {managers && managers.length === 0 && !error ? (
        <div className="qx-empty-state">There are no active Managers to assign yet.</div>
      ) : (
        <div className="qx-field">
          <label htmlFor="assign-manager">Assign Manager</label>
          <select id="assign-manager" className="qx-select" value={selected} onChange={(e) => setSelected(e.target.value)} disabled={!managers} data-testid="assign-manager-select">
            <option value="">{managers ? "Select Manager" : "Loading…"}</option>
            {managers?.map((m) => (
              <option key={m.manager_id} value={m.manager_id}>{m.display_name} ({m.manager_id})</option>
            ))}
          </select>
        </div>
      )}
      <div className="qx-modal-actions">
        <button className="qx-btn" type="button" onClick={onClose}>Cancel</button>
        <button className="qx-btn qx-btn-primary" type="button" disabled={!selected || busy} onClick={() => onConfirm(selected)} data-testid="assign-manager-confirm">
          {busy ? "Saving…" : mode === "approve" ? "Approve & Assign" : "Assign"}
        </button>
      </div>
    </Modal>
  );
}

function RejectModal({ row, busy, onClose, onConfirm }: { row: PublisherRow; busy: boolean; onClose: () => void; onConfirm: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <Modal title="Reject application" onClose={onClose}>
      <p className="qx-assign-hint">Reject <b>{row.display_name}</b>'s application? The record is kept and no Manager is assigned.</p>
      <div className="qx-field">
        <label htmlFor="reject-reason">Reason (optional, recorded in the audit log)</label>
        <textarea id="reject-reason" className="qx-textarea" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
      </div>
      <div className="qx-modal-actions">
        <button className="qx-btn" type="button" onClick={onClose}>Cancel</button>
        <button className="qx-btn qx-btn-danger-solid" type="button" disabled={busy} onClick={() => onConfirm(reason.trim())} data-testid="reject-confirm">
          {busy ? "Rejecting…" : "Reject"}
        </button>
      </div>
    </Modal>
  );
}

function InvitePublisherModal({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [result, setResult] = useState<{ invite_token: string; expires_at: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [copied, setCopied] = useState(false);

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      // Super Admin invites carry NO Manager: it is chosen later, when approving.
      const { data } = await api.post<{ invite_token: string; expires_at: string }>("/invites/publisher", {
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
    <Modal title="Invite Publisher" onClose={onClose}>
      <p className="qx-assign-hint">
        Creates a single-use registration link. The publisher registers normally; you then choose their Manager
        when you approve the application.
      </p>
      <ErrorBanner message={error} />
      {!result ? (
        <>
          <div className="qx-field">
            <label htmlFor="pub-invite-email">Email (optional — restricts the link to this address)</label>
            <input id="pub-invite-email" className="qx-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="sa-invite-email-input" />
          </div>
          <div className="qx-modal-actions">
            <button className="qx-btn" type="button" onClick={onClose}>Cancel</button>
            <button className="qx-btn qx-btn-primary" disabled={submitting} onClick={submit} data-testid="sa-invite-create-button">
              {submitting ? "Generating…" : "Generate Invite"}
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="qx-field">
            <label htmlFor="pub-invite-link">Registration link (shown once — copy it now)</label>
            <input id="pub-invite-link" className="qx-input" readOnly value={signupLink} onFocus={(e) => e.currentTarget.select()} data-testid="sa-invite-link" />
          </div>
          <div className="qx-hint">Expires {new Date(result.expires_at).toLocaleString()}</div>
          <div className="qx-modal-actions">
            <button className="qx-btn qx-btn-primary" type="button" onClick={async () => { try { await navigator.clipboard.writeText(signupLink); setCopied(true); } catch { /* clipboard unavailable */ } }}>
              {copied ? "Copied" : "Copy link"}
            </button>
            <button className="qx-btn" type="button" onClick={onClose}>Done</button>
          </div>
        </>
      )}
    </Modal>
  );
}
