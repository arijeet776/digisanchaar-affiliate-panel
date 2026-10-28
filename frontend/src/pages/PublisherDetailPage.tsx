import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ErrorBanner, StatusBadge } from "../components/Common";

interface PublisherDetail {
  user_id: string;
  publisher_id: string;
  manager_id: string | null;
  manager_name?: string | null;
  mobile?: string | null;
  company?: string | null;
  invitation_type?: string | null;
  display_name: string;
  email: string;
  account_status: string;
  email_verified: boolean;
  created_at: string;
}

export function PublisherDetailPage() {
  const { userId = "" } = useParams();
  const [publisher, setPublisher] = useState<PublisherDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<PublisherDetail>(`/publishers/${userId}`)
      .then((r) => setPublisher(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load publisher"));
  }, [userId]);

  return (
    <AppShell title="Publisher detail">
      <Link to="/publishers" style={{ fontSize: 12.5 }}>← Back to Publishers</Link>
      <ErrorBanner message={error} />

      {publisher && (
        <>
          <div className="qx-page-header" style={{ marginTop: 14 }}>
            <div>
              <div className="qx-page-title">{publisher.display_name}</div>
              <div className="qx-page-subtitle">{publisher.email}</div>
            </div>
            <StatusBadge status={publisher.account_status} />
          </div>

          <div className="qx-card">
            <div className="qx-row">
              <div>
                <div className="qx-kpi-label">Publisher ID</div>
                <div>{publisher.publisher_id}</div>
              </div>
              <div>
                <div className="qx-kpi-label">Manager</div>
                <div>
                  {publisher.manager_id ? `${publisher.manager_name ?? ""} (${publisher.manager_id})` : <span className="qx-unassigned">Not Assigned</span>}
                </div>
              </div>
              <div>
                <div className="qx-kpi-label">Mobile</div>
                <div>{publisher.mobile ?? "—"}</div>
              </div>
              <div>
                <div className="qx-kpi-label">Company</div>
                <div>{publisher.company ?? "—"}</div>
              </div>
              <div>
                <div className="qx-kpi-label">Invited by</div>
                <div>{publisher.invitation_type === "SUPER_ADMIN_INVITE" ? "Super Admin" : publisher.invitation_type === "MANAGER_INVITE" ? "Manager" : "—"}</div>
              </div>
              <div>
                <div className="qx-kpi-label">Email verified</div>
                <div>{publisher.email_verified ? "Yes" : "No"}</div>
              </div>
              <div>
                <div className="qx-kpi-label">Created</div>
                <div>{publisher.created_at ? new Date(publisher.created_at).toLocaleString() : "—"}</div>
              </div>
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}
