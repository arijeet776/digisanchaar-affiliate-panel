import { useEffect, useState } from "react";
import { AppShell } from "../../components/AppShell";
import { EmptyState, ErrorBanner, Modal, Pagination, StatusBadge } from "../../components/Common";
import { api, ApiError } from "../../api/client";

interface Overview {
  manager_id: string;
  scoped_publisher_liability: string;
  scoped_total_earned: string;
  currency: string;
}

interface Withdrawal {
  withdrawal_id: string;
  publisher_id: string;
  amount: string;
  status: string;
  requested_at: string;
}

const PAGE_SIZE = 20;

export function ManagerFinancialsPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [withdrawals, setWithdrawals] = useState<Withdrawal[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [rejectTarget, setRejectTarget] = useState<Withdrawal | null>(null);

  function load() {
    api
      .get<Overview>("/admin/financials/overview")
      .then((r) => setOverview(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load overview"));
    api
      .get<{ items: Withdrawal[]; total: number }>("/admin/financials/withdrawals", {
        status: status || undefined, page, page_size: PAGE_SIZE,
      })
      .then((r) => {
        setWithdrawals(r.data.items);
        setTotal(r.data.total);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load withdrawals"));
  }

  useEffect(load, [status, page]);

  async function approve(w: Withdrawal) {
    try {
      await api.post(`/admin/financials/withdrawals/${w.withdrawal_id}/approve`);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Approve failed");
    }
  }

  async function reject(reason: string) {
    if (!rejectTarget) return;
    try {
      await api.post(`/admin/financials/withdrawals/${rejectTarget.withdrawal_id}/reject`, { reason });
      setRejectTarget(null);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Reject failed");
    }
  }

  return (
    <AppShell title="Financials">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Financials</div>
          <div className="qx-page-subtitle">Scoped to your own publishers only.</div>
        </div>
      </div>

      <ErrorBanner message={error} />

      {overview && (
        <div className="qx-kpi-grid">
          <div className="qx-kpi-card">
            <div className="qx-kpi-label">Your Publishers' Liability</div>
            <div className="qx-kpi-value">₹{overview.scoped_publisher_liability}</div>
          </div>
          <div className="qx-kpi-card">
            <div className="qx-kpi-label">Your Publishers' Total Earned</div>
            <div className="qx-kpi-value">₹{overview.scoped_total_earned}</div>
          </div>
        </div>
      )}

      <div className="qx-section-title" style={{ marginTop: 0 }}>Withdrawal Requests</div>
      <div className="qx-row" style={{ marginBottom: 14, maxWidth: 260 }}>
        <select className="qx-select" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          <option value="requested">Requested</option>
          <option value="under_review">Under review</option>
          <option value="approved">Approved</option>
          <option value="paid">Paid</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      {withdrawals.length === 0 ? (
        <EmptyState message="No withdrawals match this filter." />
      ) : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead>
              <tr><th>Publisher</th><th>Amount</th><th>Status</th><th>Requested</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {withdrawals.map((w) => (
                <tr key={w.withdrawal_id}>
                  <td>{w.publisher_id}</td>
                  <td className="qx-amount">₹{w.amount}</td>
                  <td><StatusBadge status={w.status} /></td>
                  <td>{new Date(w.requested_at).toLocaleString()}</td>
                  <td>
                    {(w.status === "requested" || w.status === "under_review") && (
                      <div className="qx-table-actions">
                        <button className="qx-btn qx-btn-sm qx-btn-primary" onClick={() => approve(w)}>Approve</button>
                        <button className="qx-btn qx-btn-sm qx-btn-danger" onClick={() => setRejectTarget(w)}>Reject</button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} />

      {rejectTarget && (
        <Modal title="Reject withdrawal" onClose={() => setRejectTarget(null)}>
          <RejectForm onConfirm={reject} />
        </Modal>
      )}
    </AppShell>
  );
}

function RejectForm({ onConfirm }: { onConfirm: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <>
      <div className="qx-field">
        <label htmlFor="mgr-reject-reason">Reason (required, shown to the publisher)</label>
        <textarea id="mgr-reject-reason" className="qx-textarea" value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <button className="qx-btn qx-btn-danger" disabled={!reason.trim()} onClick={() => onConfirm(reason)}>Reject</button>
    </>
  );
}
