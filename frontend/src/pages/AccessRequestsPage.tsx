import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { EmptyState, ErrorBanner, Pagination, StatusBadge } from "../components/Common";

interface Row {
  access_id: string;
  campaign_id: string;
  campaign_name: string | null;
  publisher_id: string;
  publisher_name: string | null;
  status: string;
  requested_at: string;
}
const PAGE_SIZE = 20;

export function AccessRequestsPage() {
  const [items, setItems] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("pending");
  const [error, setError] = useState<string | null>(null);

  function load() {
    api
      .get<{ items: Row[]; total: number }>("/campaign-access/applications", { status: status || undefined, page, page_size: PAGE_SIZE })
      .then((r) => { setItems(r.data.items); setTotal(r.data.total); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load requests"));
  }
  useEffect(load, [page, status]);

  async function decide(id: string, action: "approve" | "reject") {
    setError(null);
    try {
      await api.post(`/campaign-access/applications/${id}/${action}`, {});
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    }
  }

  return (
    <AppShell title="Access Requests">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Access Requests</div>
          <div className="qx-page-subtitle">Publishers requesting to promote campaigns that require approval.</div>
        </div>
        <select className="qx-select" value={status} onChange={(e) => { setPage(1); setStatus(e.target.value); }} aria-label="Filter status">
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="">All</option>
        </select>
      </div>
      <ErrorBanner message={error} />
      {items.length === 0 ? <EmptyState message="No requests." /> : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead><tr><th>Publisher</th><th>Campaign</th><th>Requested</th><th>Status</th><th /></tr></thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.access_id}>
                  <td>{r.publisher_name ?? r.publisher_id}</td>
                  <td>{r.campaign_name ?? r.campaign_id} <span style={{ color: "var(--text-muted)" }}>#{r.campaign_id}</span></td>
                  <td>{new Date(r.requested_at).toLocaleString()}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td style={{ textAlign: "right" }}>
                    {r.status !== "approved" && (
                      <>
                        <button className="qx-btn qx-btn-primary qx-btn-sm" onClick={() => decide(r.access_id, "approve")}>Approve</button>{" "}
                        {r.status === "pending" && <button className="qx-btn qx-btn-sm" onClick={() => decide(r.access_id, "reject")}>Reject</button>}
                      </>
                    )}
                  </td>
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
