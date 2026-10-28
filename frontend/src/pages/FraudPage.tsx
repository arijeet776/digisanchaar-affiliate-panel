import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { EmptyState, ErrorBanner, Modal, Pagination, StatusBadge } from "../components/Common";
import { FoundationNote } from "../components/Common";

interface BlockedIp {
  id: string;
  ip_address: string;
  block_reason: string;
  campaign_id: string | null;
  publisher_id: string | null;
  manager_id: string | null;
  first_detected_at: string;
  last_detected_at: string;
  detection_count: number;
  status: "blocked" | "safe" | "permanent_block";
  under_investigation: boolean;
  detection_source: string;
}

interface Overview {
  blocked: number;
  permanent_block: number;
  safe: number;
  under_investigation: number;
}

const PAGE_SIZE = 20;

export function FraudPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [rows, setRows] = useState<BlockedIp[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);

  function load() {
    api.get<Overview>("/admin/fraud/overview").then((r) => setOverview(r.data)).catch(() => setOverview(null));
    api
      .get<BlockedIp[]>("/admin/fraud/blocked-ips", { status: status || undefined, page, page_size: PAGE_SIZE })
      .then((r) => {
        setRows(r.data);
        setTotal(r.totalCount ?? r.data.length);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load fraud registry"));
  }

  useEffect(load, [status, page]);

  async function act(id: string, action: "mark-safe" | "keep-blocked" | "permanent-block" | "investigate" | "close-investigation") {
    try {
      await api.post(`/admin/fraud/blocked-ips/${id}/${action}`);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    }
  }

  return (
    <AppShell title="Fraud & Security">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Fraud & Security</div>
          <div className="qx-page-subtitle">Blocked-IP registry and review workflow.</div>
        </div>
        <button className="qx-btn qx-btn-primary" onClick={() => setAddOpen(true)}>
          + Register IP
        </button>
      </div>

      <FoundationNote>
        Manage blocked IP addresses here. Blocked Devices, Suspicious Activity and automated Fraud
        Rules appear once enough live tracking and conversion data exists to generate real signals. IP alone is never treated as definitive
        proof of fraud — enforcement combines IP, device signals, velocity and behavioral patterns
        before any decision.
      </FoundationNote>

      <ErrorBanner message={error} />

      {overview && (
        <div className="qx-kpi-grid" style={{ marginTop: 16 }}>
          <div className="qx-kpi-card"><div className="qx-kpi-label">Blocked</div><div className="qx-kpi-value">{overview.blocked}</div></div>
          <div className="qx-kpi-card"><div className="qx-kpi-label">Permanently blocked</div><div className="qx-kpi-value">{overview.permanent_block}</div></div>
          <div className="qx-kpi-card"><div className="qx-kpi-label">Marked safe</div><div className="qx-kpi-value">{overview.safe}</div></div>
          <div className="qx-kpi-card"><div className="qx-kpi-label">Under investigation</div><div className="qx-kpi-value">{overview.under_investigation}</div></div>
        </div>
      )}

      <div className="qx-row" style={{ marginBottom: 14, maxWidth: 260 }}>
        <select className="qx-select" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          <option value="blocked">Blocked</option>
          <option value="safe">Safe</option>
          <option value="permanent_block">Permanent block</option>
        </select>
      </div>

      {rows.length === 0 ? (
        <EmptyState message="No blocked IPs match this filter." />
      ) : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead>
              <tr>
                <th>IP address</th>
                <th>Reason</th>
                <th>Status</th>
                <th>Detections</th>
                <th>Last detected</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.id}>
                  <td style={{ fontFamily: "monospace" }}>
                    {b.ip_address} {b.under_investigation && <span className="qx-badge pending">investigating</span>}
                  </td>
                  <td>{b.block_reason}</td>
                  <td><StatusBadge status={b.status} /></td>
                  <td>{b.detection_count}</td>
                  <td>{new Date(b.last_detected_at).toLocaleString()}</td>
                  <td>
                    <div className="qx-table-actions">
                      {b.status !== "safe" && (
                        <button className="qx-btn qx-btn-sm" onClick={() => act(b.id, "mark-safe")}>Mark safe</button>
                      )}
                      {b.status === "blocked" && (
                        <>
                          <button className="qx-btn qx-btn-sm" onClick={() => act(b.id, "keep-blocked")}>Keep blocked</button>
                          <button className="qx-btn qx-btn-sm qx-btn-danger" onClick={() => act(b.id, "permanent-block")}>Permanent block</button>
                        </>
                      )}
                      <button className="qx-btn qx-btn-sm" onClick={() => act(b.id, b.under_investigation ? "close-investigation" : "investigate")}>
                        {b.under_investigation ? "Close investigation" : "Investigate"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} />

      {addOpen && <AddBlockedIpModal onClose={() => setAddOpen(false)} onCreated={load} />}
    </AppShell>
  );
}

function AddBlockedIpModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [ip, setIp] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/admin/fraud/blocked-ips", { ip_address: ip, block_reason: reason, detection_source: "manual" });
      onCreated();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to register IP");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="Register a blocked IP" onClose={onClose}>
      <ErrorBanner message={error} />
      <div className="qx-field">
        <label htmlFor="ip">IP address</label>
        <input id="ip" className="qx-input" value={ip} onChange={(e) => setIp(e.target.value)} placeholder="203.0.113.7" required />
      </div>
      <div className="qx-field">
        <label htmlFor="reason">Block reason</label>
        <textarea id="reason" className="qx-textarea" value={reason} onChange={(e) => setReason(e.target.value)} required />
      </div>
      <button className="qx-btn qx-btn-primary" disabled={submitting || !ip.trim() || !reason.trim()} onClick={submit}>
        {submitting ? "Registering…" : "Register IP"}
      </button>
    </Modal>
  );
}
