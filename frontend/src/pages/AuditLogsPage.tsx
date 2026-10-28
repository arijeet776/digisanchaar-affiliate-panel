import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { EmptyState, ErrorBanner, Pagination } from "../components/Common";

interface AuditLog {
  action: string;
  actor_user_id: string | null;
  target_user_id: string | null;
  reason: string | null;
  metadata: Record<string, unknown>;
  request_id: string | null;
  timestamp: string;
}

const PAGE_SIZE = 25;

export function AuditLogsPage() {
  const [params, setParams] = useSearchParams();
  const action = params.get("action") ?? "";
  const page = parseInt(params.get("page") ?? "1", 10);

  const [rows, setRows] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AuditLog[]>("/admin/audit-logs", { action: action || undefined, page, page_size: PAGE_SIZE })
      .then((r) => {
        setRows(r.data);
        setTotal(r.totalCount ?? r.data.length);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load audit logs"));
  }, [action, page]);

  return (
    <AppShell title="Audit Logs">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Audit Logs</div>
          <div className="qx-page-subtitle">Every privileged action, who did it, and when. No secrets are ever stored here.</div>
        </div>
      </div>

      <ErrorBanner message={error} />

      <div className="qx-row" style={{ marginBottom: 14, maxWidth: 320 }}>
        <select className="qx-select" value={action} onChange={(e) => setParams({ action: e.target.value, page: "1" })}>
          <option value="">All actions</option>
          <option value="CAMPAIGN_CREATED">Campaign created</option>
          <option value="CAMPAIGN_UPDATED">Campaign updated</option>
          <option value="CAMPAIGN_PAUSED">Campaign paused</option>
          <option value="CAMPAIGN_RESUMED">Campaign resumed</option>
          <option value="CAMPAIGN_ENDED">Campaign ended</option>
          <option value="MANAGER_APPROVED">Manager approved</option>
          <option value="MANAGER_REJECTED">Manager rejected</option>
          <option value="PUBLISHER_APPROVED">Publisher approved</option>
          <option value="PUBLISHER_REJECTED">Publisher rejected</option>
          <option value="LOGIN_SUCCESS">Login success</option>
          <option value="LOGIN_FAILED">Login failed</option>
        </select>
      </div>

      {rows.length === 0 ? (
        <EmptyState message="No audit events match this filter." />
      ) : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Action</th>
                <th>Actor</th>
                <th>Target</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((log, i) => (
                <tr key={i}>
                  <td>{new Date(log.timestamp).toLocaleString()}</td>
                  <td>{log.action.replace(/_/g, " ")}</td>
                  <td style={{ fontFamily: "monospace", fontSize: 11.5 }}>{log.actor_user_id ?? "—"}</td>
                  <td style={{ fontFamily: "monospace", fontSize: 11.5 }}>{log.target_user_id ?? "—"}</td>
                  <td>{log.reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onChange={(p) => setParams({ action, page: String(p) })} />
    </AppShell>
  );
}
