import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { EmptyState, ErrorBanner, StatusBadge } from "../components/Common";

interface ManagerDetail {
  user_id: string;
  email: string;
  account_status: string;
  email_verified: boolean;
  created_at: string;
  manager_id: string | null;
  display_name: string | null;
}

interface PublisherRow {
  user_id: string;
  publisher_id: string;
  display_name: string;
}

export function ManagerDetailPage() {
  const { userId = "" } = useParams();
  const [manager, setManager] = useState<ManagerDetail | null>(null);
  const [publishers, setPublishers] = useState<PublisherRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ManagerDetail>(`/admin/managers/${userId}`)
      .then((r) => setManager(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load manager"));
    api
      .get<PublisherRow[]>(`/admin/managers/${userId}/publishers`)
      .then((r) => setPublishers(r.data))
      .catch(() => setPublishers([]));
  }, [userId]);

  return (
    <AppShell title="Manager detail">
      <Link to="/managers" style={{ fontSize: 12.5 }}>← Back to Managers</Link>
      <ErrorBanner message={error} />

      {manager && (
        <>
          <div className="qx-page-header" style={{ marginTop: 14 }}>
            <div>
              <div className="qx-page-title">{manager.display_name ?? manager.email}</div>
              <div className="qx-page-subtitle">{manager.email}</div>
            </div>
            <StatusBadge status={manager.account_status} />
          </div>

          <div className="qx-card" style={{ marginBottom: 20 }}>
            <div className="qx-row">
              <div>
                <div className="qx-kpi-label">Manager ID</div>
                <div>{manager.manager_id ?? "—"}</div>
              </div>
              <div>
                <div className="qx-kpi-label">Email verified</div>
                <div>{manager.email_verified ? "Yes" : "No"}</div>
              </div>
              <div>
                <div className="qx-kpi-label">Created</div>
                <div>{new Date(manager.created_at).toLocaleString()}</div>
              </div>
            </div>
          </div>

          <div className="qx-section-title">Assigned Publishers</div>
          {publishers.length === 0 ? (
            <EmptyState message="No publishers assigned yet." />
          ) : (
            <div className="qx-table-wrap">
              <table className="qx-table">
                <thead>
                  <tr>
                    <th>Publisher ID</th>
                    <th>Name</th>
                  </tr>
                </thead>
                <tbody>
                  {publishers.map((p) => (
                    <tr key={p.user_id}>
                      <td>
                        <Link to={`/publishers/${p.user_id}`}>{p.publisher_id}</Link>
                      </td>
                      <td>{p.display_name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </AppShell>
  );
}
