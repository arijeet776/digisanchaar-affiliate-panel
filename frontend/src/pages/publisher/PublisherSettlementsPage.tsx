import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../components/AppShell";
import { EmptyState, ErrorBanner, Pagination, StatusBadge } from "../../components/Common";
import { IconFinancial, IconLink, IconReports } from "../../components/Icons";

interface Withdrawal {
  withdrawal_id: string; amount: string; status: string; requested_at: string;
  reference: string | null; rejection_reason: string | null;
}
const PAGE_SIZE = 10;
const TABS = [
  { key: "", label: "ALL" },
  { key: "paid", label: "PAID" },
  { key: "requested,under_review,approved", label: "PENDING" },
  { key: "cancelled,rejected", label: "CANCELLED" },
];

export function PublisherSettlementsPage() {
  const [items, setItems] = useState<Withdrawal[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [tab, setTab] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<{ items: Withdrawal[]; total: number }>("/wallet/withdrawals", { page, page_size: PAGE_SIZE })
      .then((r) => { setItems(r.data.items); setTotal(r.data.total); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load settlements"));
  }, [page]);

  const filtered = useMemo(() => {
    const statuses = tab ? tab.split(",") : null;
    return items.filter((w) => {
      if (statuses && !statuses.includes(w.status)) return false;
      if (search && !(w.withdrawal_id.toLowerCase().includes(search.toLowerCase()) || (w.reference ?? "").toLowerCase().includes(search.toLowerCase()))) return false;
      return true;
    });
  }, [items, tab, search]);

  const totalPaid = items.filter((w) => w.status === "paid").reduce((s, w) => s + parseFloat(w.amount), 0);
  const pending = items.filter((w) => ["requested", "under_review", "approved"].includes(w.status)).reduce((s, w) => s + parseFloat(w.amount), 0);
  const lastPaid = items.filter((w) => w.status === "paid").sort((a, b) => b.requested_at.localeCompare(a.requested_at))[0];

  return (
    <AppShell title="Payout Settlements">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Payout Settlements</div>
          <div className="qx-page-subtitle">Track monthly payout statements, view campaign conversions, and download invoice receipts.</div>
        </div>
      </div>
      <ErrorBanner message={error} />
      <div className="qx-kpi-grid">
        <div className="qx-kpi-card">
          <div className="qx-kpi-icon"><IconFinancial width={16} height={16} /></div>
          <div className="qx-kpi-label">Total Paid Out</div>
          <div className="qx-kpi-value">₹{totalPaid.toFixed(2)}</div>
          <div className="qx-hint">Accumulated lifetime payouts released.</div>
        </div>
        <div className="qx-kpi-card">
          <div className="qx-kpi-icon"><IconReports width={16} height={16} /></div>
          <div className="qx-kpi-label">Pending Statements</div>
          <div className="qx-kpi-value">₹{pending.toFixed(2)}</div>
          <div className="qx-hint">Awaiting bank transfer clearance.</div>
        </div>
        <div className="qx-kpi-card">
          <div className="qx-kpi-icon"><IconLink width={16} height={16} /></div>
          <div className="qx-kpi-label">Total Statements</div>
          <div className="qx-kpi-value">{items.filter((w) => w.status === "paid").length}</div>
          <div className="qx-hint">Released monthly invoice ledgers.</div>
        </div>
        <div className="qx-kpi-card">
          <div className="qx-kpi-icon"><IconReports width={16} height={16} /></div>
          <div className="qx-kpi-label">Last Paid Date</div>
          <div className="qx-kpi-value" style={{ fontSize: 18 }}>{lastPaid ? new Date(lastPaid.requested_at).toLocaleDateString() : "No releases yet"}</div>
          <div className="qx-hint">Timestamp of last successful clearance.</div>
        </div>
      </div>

      <div className="qx-card" style={{ marginBottom: 14 }}>
        <input className="qx-input" placeholder="Search by Invoice INV or UTR…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="qx-tab-row" style={{ marginTop: 10 }}>
          {TABS.map((t) => (
            <button key={t.key} className={`qx-tab ${tab === t.key ? "active" : ""}`} onClick={() => setTab(t.key)}>{t.label}</button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyState message="You don't have any payout statements generated yet. Statements are released month-wise by our admins." />
      ) : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead><tr><th>Requested</th><th>Amount</th><th>Status</th><th>Reference</th></tr></thead>
            <tbody>
              {filtered.map((w) => (
                <tr key={w.withdrawal_id}>
                  <td>{new Date(w.requested_at).toLocaleDateString()}</td>
                  <td className="qx-amount">₹{w.amount}</td>
                  <td><StatusBadge status={w.status} /></td>
                  <td>{w.status === "rejected" ? w.rejection_reason : w.reference ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} />
    </AppShell>
  );
}
