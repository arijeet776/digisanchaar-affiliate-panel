import { useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { EmptyState, ErrorBanner, Modal, Pagination, StatusBadge } from "../components/Common";
import { api, ApiError } from "../api/client";

interface Overview {
  total_publisher_liability: string;
  total_earned: string;
  total_reversed: string;
  held_amount: string;
  currency: string;
  withdrawals_pending_count: number;
  withdrawals_approved_count: number;
  withdrawals_paid_count: number;
  withdrawals_rejected_count: number;
}

interface LedgerEntry {
  ledger_id: string;
  transaction_type: string;
  direction: string;
  publisher_id: string;
  amount: string;
  campaign_id: string | null;
  conversion_id: string | null;
  withdrawal_id: string | null;
  reference: string | null;
  created_at: string;
}

interface Withdrawal {
  withdrawal_id: string;
  publisher_id: string;
  manager_id: string | null;
  amount: string;
  currency: string;
  status: string;
  reference: string | null;
  rejection_reason: string | null;
  requested_at: string;
  updated_at: string;
}

const PAGE_SIZE = 20;

export function FinancialsPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [withdrawals, setWithdrawals] = useState<Withdrawal[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [rejectTarget, setRejectTarget] = useState<Withdrawal | null>(null);
  const [payTarget, setPayTarget] = useState<Withdrawal | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [ledgerTotal, setLedgerTotal] = useState(0);
  const [ledgerPage, setLedgerPage] = useState(1);

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

  function loadLedger() {
    api
      .get<{ items: LedgerEntry[]; total: number }>("/admin/financials/ledger", {
        page: ledgerPage, page_size: PAGE_SIZE,
      })
      .then((r) => {
        setLedger(r.data.items);
        setLedgerTotal(r.data.total);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load ledger"));
  }

  useEffect(loadLedger, [ledgerPage]);

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

  async function markPaid(reference: string) {
    if (!payTarget) return;
    try {
      await api.post(`/admin/financials/withdrawals/${payTarget.withdrawal_id}/mark-paid`, { reference: reference || null });
      setPayTarget(null);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Mark-paid failed");
    }
  }

  return (
    <AppShell title="Financials">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Financials</div>
          <div className="qx-page-subtitle">
            Network-wide financial overview. The ledger is the single source of truth for all balances.
          </div>
        </div>
      </div>

      <ErrorBanner message={error} />

      {overview && (
        <div className="qx-kpi-grid">
          <div className="qx-kpi-card">
            <div className="qx-kpi-label">Total Publisher Liability</div>
            <div className="qx-kpi-value">₹{overview.total_publisher_liability}</div>
          </div>
          <div className="qx-kpi-card">
            <div className="qx-kpi-label">Total Earned (all-time)</div>
            <div className="qx-kpi-value">₹{overview.total_earned}</div>
          </div>
          <div className="qx-kpi-card">
            <div className="qx-kpi-label">Pending Withdrawals</div>
            <div className="qx-kpi-value">{overview.withdrawals_pending_count}</div>
          </div>
          <div className="qx-kpi-card">
            <div className="qx-kpi-label">Approved (awaiting payment)</div>
            <div className="qx-kpi-value">{overview.withdrawals_approved_count}</div>
          </div>
          <div className="qx-kpi-card">
            <div className="qx-kpi-label">Paid</div>
            <div className="qx-kpi-value">{overview.withdrawals_paid_count}</div>
          </div>
          <div className="qx-kpi-card">
            <div className="qx-kpi-label">Rejected</div>
            <div className="qx-kpi-value">{overview.withdrawals_rejected_count}</div>
          </div>
          <div className="qx-kpi-card">
            <div className="qx-kpi-label">Held (pending withdrawals)</div>
            <div className="qx-kpi-value">₹{overview.held_amount}</div>
          </div>
          {parseFloat(overview.total_reversed) > 0 && (
            <div className="qx-kpi-card">
              <div className="qx-kpi-label">Reversed (chargebacks)</div>
              <div className="qx-kpi-value">₹{overview.total_reversed}</div>
            </div>
          )}
        </div>
      )}

      <div className="qx-section-title" style={{ marginTop: 0 }}>Withdrawal Operations</div>
      <div className="qx-row" style={{ marginBottom: 14, maxWidth: 260 }}>
        <select className="qx-select" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          <option value="requested">Requested</option>
          <option value="under_review">Under review</option>
          <option value="approved">Approved</option>
          <option value="paid">Paid</option>
          <option value="rejected">Rejected</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {withdrawals.length === 0 ? (
        <EmptyState message="No withdrawals match this filter." />
      ) : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead>
              <tr>
                <th>Publisher</th><th>Manager</th><th>Amount</th><th>Status</th><th>Requested</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {withdrawals.map((w) => (
                <tr key={w.withdrawal_id}>
                  <td>{w.publisher_id}</td>
                  <td>{w.manager_id ?? "—"}</td>
                  <td className="qx-amount">₹{w.amount}</td>
                  <td><StatusBadge status={w.status} /></td>
                  <td>{new Date(w.requested_at).toLocaleString()}</td>
                  <td>
                    <div className="qx-table-actions">
                      {(w.status === "requested" || w.status === "under_review") && (
                        <>
                          <button className="qx-btn qx-btn-sm qx-btn-primary" onClick={() => approve(w)}>Approve</button>
                          <button className="qx-btn qx-btn-sm qx-btn-danger" onClick={() => setRejectTarget(w)}>Reject</button>
                        </>
                      )}
                      {w.status === "approved" && (
                        <button className="qx-btn qx-btn-sm qx-btn-primary" onClick={() => setPayTarget(w)}>Mark Paid</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} />

      <div className="qx-section-title">Network Ledger (immutable, append-only)</div>
      {ledger.length === 0 ? (
        <EmptyState message="No ledger activity yet." />
      ) : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead>
              <tr><th>Type</th><th>Publisher</th><th>Amount</th><th>Campaign</th><th>Reference</th><th>Date</th></tr>
            </thead>
            <tbody>
              {ledger.map((l) => (
                <tr key={l.ledger_id}>
                  <td style={{ textTransform: "capitalize" }}>{l.transaction_type.replace(/_/g, " ")}</td>
                  <td>{l.publisher_id}</td>
                  <td className={`qx-amount ${l.direction === "credit" ? "positive" : ""}`}>
                    {l.direction === "credit" ? "+" : "-"}₹{l.amount}
                  </td>
                  <td>{l.campaign_id ?? "—"}</td>
                  <td>{l.reference ?? "—"}</td>
                  <td>{new Date(l.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination page={ledgerPage} pageSize={PAGE_SIZE} total={ledgerTotal} onChange={setLedgerPage} />

      {rejectTarget && (
        <RejectModal onClose={() => setRejectTarget(null)} onConfirm={reject} />
      )}
      {payTarget && (
        <PayModal onClose={() => setPayTarget(null)} onConfirm={markPaid} />
      )}
    </AppShell>
  );
}

function RejectModal({ onClose, onConfirm }: { onClose: () => void; onConfirm: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <Modal title="Reject withdrawal" onClose={onClose}>
      <div className="qx-field">
        <label htmlFor="reject-reason">Reason (required, shown to the publisher)</label>
        <textarea id="reject-reason" className="qx-textarea" value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button className="qx-btn" onClick={onClose}>Cancel</button>
        <button className="qx-btn qx-btn-danger" disabled={!reason.trim()} onClick={() => onConfirm(reason)}>Reject</button>
      </div>
    </Modal>
  );
}

function PayModal({ onClose, onConfirm }: { onClose: () => void; onConfirm: (reference: string) => void }) {
  const [reference, setReference] = useState("");
  return (
    <Modal title="Mark withdrawal as paid" onClose={onClose}>
      <div className="qx-field">
        <label htmlFor="pay-reference">Payment reference (optional — UTR/transaction id)</label>
        <input id="pay-reference" className="qx-input" value={reference} onChange={(e) => setReference(e.target.value)} />
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button className="qx-btn" onClick={onClose}>Cancel</button>
        <button className="qx-btn qx-btn-primary" onClick={() => onConfirm(reference)}>Mark Paid</button>
      </div>
    </Modal>
  );
}
