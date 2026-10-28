import { useEffect, useState } from "react";
import { AppShell } from "../../components/AppShell";
import { EmptyState, ErrorBanner, Modal, Pagination, StatusBadge } from "../../components/Common";
import { api, ApiError } from "../../api/client";

interface WalletSummary {
  publisher_id: string;
  available_balance: string;
  total_earned: string;
  total_reversed: string;
  held_amount: string;
  currency: string;
}

interface LedgerEntry {
  ledger_id: string;
  transaction_type: string;
  direction: string;
  amount: string;
  campaign_id: string | null;
  conversion_id: string | null;
  reference: string | null;
  created_at: string;
}

interface Withdrawal {
  withdrawal_id: string;
  amount: string;
  status: string;
  reference: string | null;
  rejection_reason: string | null;
  requested_at: string;
}

const PAGE_SIZE = 20;
const MIN_WITHDRAWAL = 100;

export function PublisherWalletPage() {
  const [wallet, setWallet] = useState<WalletSummary | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [withdrawals, setWithdrawals] = useState<Withdrawal[]>([]);
  const [wdTotal, setWdTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [requestOpen, setRequestOpen] = useState(false);

  function load() {
    api.get<WalletSummary>("/wallet/summary").then((r) => setWallet(r.data)).catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load wallet"));
    api.get<{ items: LedgerEntry[] }>("/wallet/ledger", { page_size: 10 }).then((r) => setLedger(r.data.items)).catch(() => setLedger([]));
    api
      .get<{ items: Withdrawal[]; total: number }>("/wallet/withdrawals", { page, page_size: PAGE_SIZE })
      .then((r) => { setWithdrawals(r.data.items); setWdTotal(r.data.total); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load withdrawals"));
  }

  useEffect(load, [page]);

  async function cancel(withdrawalId: string) {
    try {
      await api.post(`/wallet/withdrawals/${withdrawalId}/cancel`);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Cancel failed");
    }
  }

  const canWithdraw = wallet ? parseFloat(wallet.available_balance) >= MIN_WITHDRAWAL : false;

  return (
    <AppShell title="Wallet">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Wallet</div>
          <div className="qx-page-subtitle">Your balance, earnings, and withdrawal history.</div>
        </div>
        <button className="qx-btn qx-btn-primary" disabled={!canWithdraw} onClick={() => setRequestOpen(true)}>
          Request Withdrawal
        </button>
      </div>

      <ErrorBanner message={error} />

      {wallet && (
        <div className="qx-kpi-grid">
          <div className="qx-kpi-card">
            <div className="qx-kpi-label">Available Balance</div>
            <div className="qx-kpi-value">₹{wallet.available_balance}</div>
          </div>
          <div className="qx-kpi-card">
            <div className="qx-kpi-label">Total Earned</div>
            <div className="qx-kpi-value">₹{wallet.total_earned}</div>
          </div>
          <div className="qx-kpi-card">
            <div className="qx-kpi-label">Held (pending withdrawal)</div>
            <div className="qx-kpi-value">₹{wallet.held_amount}</div>
          </div>
          {parseFloat(wallet.total_reversed) > 0 && (
            <div className="qx-kpi-card">
              <div className="qx-kpi-label">Reversed</div>
              <div className="qx-kpi-value">₹{wallet.total_reversed}</div>
            </div>
          )}
        </div>
      )}
      {wallet && !canWithdraw && (
        <div className="qx-hint" style={{ marginBottom: 16 }}>
          Minimum withdrawal is ₹{MIN_WITHDRAWAL}. Keep earning to unlock a withdrawal request.
        </div>
      )}

      <div className="qx-section-title" style={{ marginTop: 0 }}>Recent Earnings</div>
      {ledger.length === 0 ? (
        <EmptyState message="No earnings yet." />
      ) : (
        <div className="qx-table-wrap" style={{ marginBottom: 24 }}>
          <table className="qx-table">
            <thead><tr><th>Type</th><th>Amount</th><th>Campaign</th><th>Date</th></tr></thead>
            <tbody>
              {ledger.map((l) => (
                <tr key={l.ledger_id}>
                  <td style={{ textTransform: "capitalize" }}>{l.transaction_type.replace(/_/g, " ")}</td>
                  <td className={`qx-amount ${l.direction === "credit" ? "positive" : ""}`}>
                    {l.direction === "credit" ? "+" : "-"}₹{l.amount}
                  </td>
                  <td>{l.campaign_id ?? "—"}</td>
                  <td>{new Date(l.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="qx-section-title">Withdrawal History</div>
      {withdrawals.length === 0 ? (
        <EmptyState message="No withdrawal requests yet." />
      ) : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead><tr><th>Amount</th><th>Status</th><th>Requested</th><th>Reference / Reason</th><th></th></tr></thead>
            <tbody>
              {withdrawals.map((w) => (
                <tr key={w.withdrawal_id}>
                  <td className="qx-amount">₹{w.amount}</td>
                  <td><StatusBadge status={w.status} /></td>
                  <td>{new Date(w.requested_at).toLocaleString()}</td>
                  <td>{w.status === "rejected" ? w.rejection_reason : w.reference ?? "—"}</td>
                  <td>
                    {w.status === "requested" && (
                      <button className="qx-btn qx-btn-sm" onClick={() => cancel(w.withdrawal_id)}>Cancel</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination page={page} pageSize={PAGE_SIZE} total={wdTotal} onChange={setPage} />

      {requestOpen && wallet && (
        <RequestWithdrawalModal
          maxAmount={parseFloat(wallet.available_balance)}
          onClose={() => setRequestOpen(false)}
          onSuccess={() => { setRequestOpen(false); load(); }}
        />
      )}
    </AppShell>
  );
}

function RequestWithdrawalModal({ maxAmount, onClose, onSuccess }: { maxAmount: number; onClose: () => void; onSuccess: () => void }) {
  const [amount, setAmount] = useState(String(Math.min(maxAmount, MIN_WITHDRAWAL)));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/wallet/withdrawals", { amount: parseFloat(amount), idempotency_key: crypto.randomUUID() });
      onSuccess();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Request failed");
    } finally {
      setSubmitting(false);
    }
  }

  const value = parseFloat(amount);
  const valid = !isNaN(value) && value >= MIN_WITHDRAWAL && value <= maxAmount;

  return (
    <Modal title="Request Withdrawal" onClose={onClose}>
      <ErrorBanner message={error} />
      <div className="qx-field">
        <label htmlFor="wd-amount">Amount (₹{MIN_WITHDRAWAL} minimum, ₹{maxAmount.toFixed(2)} available)</label>
        <input id="wd-amount" className="qx-input" type="number" min={MIN_WITHDRAWAL} max={maxAmount} value={amount} onChange={(e) => setAmount(e.target.value)} />
      </div>
      <button className="qx-btn qx-btn-primary" disabled={!valid || submitting} onClick={submit}>
        {submitting ? "Submitting…" : "Submit Request"}
      </button>
    </Modal>
  );
}
