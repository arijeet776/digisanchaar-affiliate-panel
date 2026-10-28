import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { EmptyState, ErrorBanner, Modal, Pagination, StatusBadge } from "../components/Common";

// One row per DigiSNR click ID. Each event (Install, Register, KYC, ...) is a badge on that row.
interface EventRow {
  conversion_id: string; event: string | null; status: string | null; approval_status: string;
  payout: number | null; postback_received_at: string | null; conversion_created_at: string | null;
}
interface Group {
  digisnr_click_id: string; campaign_id: string; publisher_id: string; date: string | null;
  events: EventRow[]; total_payout: number;
}
const PAGE_SIZE = 20;

export function ConversionReviewPage() {
  const [items, setItems] = useState<Group[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("pending_report");
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<{ ev: EventRow; action: "confirm" | "reject" } | null>(null);
  const [note, setNote] = useState("");

  function load() {
    api
      .get<{ items: Group[]; total: number }>("/admin/conversion-review/grouped", { approval_status: filter || undefined, page, page_size: PAGE_SIZE })
      .then((r) => { setItems(r.data.items); setTotal(r.data.total); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load conversions"));
  }
  useEffect(load, [page, filter]);

  async function submit() {
    if (!target) return;
    try {
      await api.post(`/admin/conversion-review/${target.ev.conversion_id}/${target.action}`, { note: note || null });
      setTarget(null);
      setNote("");
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
      setTarget(null);
    }
  }

  return (
    <AppShell title="Conversion Review">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Conversion Review</div>
          <div className="qx-page-subtitle">
            One row per click. Record the company's final report per event. Confirming credits the publisher; rejecting never credits (or reverses a credited conversion).
          </div>
        </div>
        <select className="qx-select" value={filter} onChange={(e) => { setPage(1); setFilter(e.target.value); }} aria-label="Filter">
          <option value="pending_report">Awaiting company report</option>
          <option value="confirmed">Confirmed</option>
          <option value="rejected">Rejected</option>
          <option value="">All</option>
        </select>
      </div>
      <ErrorBanner message={error} />
      {items.length === 0 ? <EmptyState message="No conversions." /> : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead><tr><th>Date</th><th>Click ID</th><th>Campaign</th><th>Publisher</th><th>Events</th><th>Total payout</th></tr></thead>
            <tbody>
              {items.map((g) => (
                <tr key={g.digisnr_click_id}>
                  <td>{g.date ? new Date(g.date).toLocaleString() : "—"}</td>
                  <td><code>{g.digisnr_click_id}</code></td>
                  <td>{g.campaign_id}</td>
                  <td>{g.publisher_id}</td>
                  <td>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {g.events.map((ev) => (
                        <div key={ev.conversion_id} style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6 }}>
                          <span className="qx-tag ok">{ev.event ?? "Unspecified"} · {ev.payout != null ? `₹${ev.payout}` : "—"}</span>
                          <StatusBadge status={ev.approval_status} />
                          {ev.approval_status === "pending_report" && (
                            <>
                              <button className="qx-btn qx-btn-primary qx-btn-sm" onClick={() => setTarget({ ev, action: "confirm" })}>Confirm</button>
                              <button className="qx-btn qx-btn-sm" onClick={() => setTarget({ ev, action: "reject" })}>Reject</button>
                            </>
                          )}
                          {ev.approval_status === "confirmed" && (
                            <button className="qx-btn qx-btn-sm" onClick={() => setTarget({ ev, action: "reject" })}>Reverse</button>
                          )}
                        </div>
                      ))}
                    </div>
                  </td>
                  <td>{g.total_payout ? `₹${g.total_payout}` : "₹0"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} />
      {target && (
        <Modal title={target.action === "confirm" ? "Confirm conversion" : "Reject conversion"} onClose={() => setTarget(null)}>
          <div className="qx-hint" style={{ marginBottom: 10 }}>Event: <strong>{target.ev.event ?? "Unspecified"}</strong></div>
          <div className="qx-field">
            <label htmlFor="cr-note">Note (optional)</label>
            <input id="cr-note" className="qx-input" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <button className="qx-btn qx-btn-primary" onClick={submit}>{target.action === "confirm" ? "Confirm & credit" : "Reject"}</button>
        </Modal>
      )}
    </AppShell>
  );
}
