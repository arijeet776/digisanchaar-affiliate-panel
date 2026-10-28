import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ErrorBanner, KpiCard } from "../components/Common";
import { IconAudit, IconShield } from "../components/Icons";

interface Overview {
  audit_events_24h: number;
  login_failures_24h: number;
  open_support_tickets: number;
  blocked_ips: number;
  ips_under_investigation: number;
}

interface SessionRow {
  jti: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  is_live: boolean;
}

function metric(value: number) {
  return { available: true, value, reason: null };
}

export function SecurityOpsPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [lookupUserId, setLookupUserId] = useState("");
  const [sessions, setSessions] = useState<SessionRow[] | null>(null);
  const [sessionsUserId, setSessionsUserId] = useState<string | null>(null);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  function loadOverview() {
    api
      .get<Overview>("/admin/security/overview")
      .then((r) => setOverview(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load security overview"));
  }

  useEffect(loadOverview, []);

  function lookupSessions() {
    const userId = lookupUserId.trim();
    if (!userId) return;
    setSessionsError(null);
    setSessions(null);
    api
      .get<SessionRow[]>(`/admin/security/users/${encodeURIComponent(userId)}/sessions`)
      .then((r) => {
        setSessions(r.data);
        setSessionsUserId(userId);
      })
      .catch((e) => setSessionsError(e instanceof ApiError ? e.message : "Could not look up sessions for that user id"));
  }

  async function revokeSession(jti: string) {
    setBusy(jti);
    setSessionsError(null);
    try {
      await api.post(`/admin/security/sessions/${jti}/revoke`);
      lookupSessions();
    } catch (e) {
      setSessionsError(e instanceof ApiError ? e.message : "Could not revoke session");
    } finally {
      setBusy(null);
    }
  }

  async function revokeAll() {
    if (!sessionsUserId) return;
    setBusy("all");
    setSessionsError(null);
    try {
      await api.post(`/admin/security/users/${encodeURIComponent(sessionsUserId)}/sessions/revoke-all`);
      lookupSessions();
    } catch (e) {
      setSessionsError(e instanceof ApiError ? e.message : "Could not revoke all sessions");
    } finally {
      setBusy(null);
    }
  }

  return (
    <AppShell title="Security & Sessions">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Security & Sessions</div>
          <div className="qx-page-subtitle">Network-wide operational security signals and per-user session control.</div>
        </div>
      </div>

      <ErrorBanner message={error} />

      {overview && (
        <div className="qx-kpi-grid" style={{ marginBottom: 24 }}>
          <KpiCard label="Audit Events (24h)" metric={metric(overview.audit_events_24h)} icon={IconAudit} />
          <KpiCard label="Login Failures (24h)" metric={metric(overview.login_failures_24h)} icon={IconShield} />
          <KpiCard label="Open Support Tickets" metric={metric(overview.open_support_tickets)} icon={IconAudit} />
          <KpiCard label="Blocked IPs" metric={metric(overview.blocked_ips)} icon={IconShield} />
          <KpiCard label="IPs Under Investigation" metric={metric(overview.ips_under_investigation)} icon={IconShield} />
        </div>
      )}

      <div className="qx-page-header" style={{ marginTop: 8 }}>
        <div>
          <div className="qx-page-title" style={{ fontSize: 15 }}>Session Management</div>
          <div className="qx-page-subtitle">Look up a user by their internal user id to view and revoke their active sessions.</div>
        </div>
      </div>

      <div className="qx-row" style={{ marginBottom: 14, gap: 8, maxWidth: 480 }}>
        <input
          className="qx-input"
          placeholder="user_id"
          value={lookupUserId}
          onChange={(e) => setLookupUserId(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && lookupSessions()}
        />
        <button className="qx-btn qx-btn-primary" onClick={lookupSessions} disabled={!lookupUserId.trim()}>
          Look Up
        </button>
      </div>

      <ErrorBanner message={sessionsError} />

      {sessions && (
        <>
          <div className="qx-table-wrap">
            <table className="qx-table">
              <thead>
                <tr>
                  <th>Session (jti)</th>
                  <th>Created</th>
                  <th>Expires</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sessions.length === 0 ? (
                  <tr>
                    <td colSpan={5} style={{ color: "var(--text-secondary)" }}>No sessions found for this user.</td>
                  </tr>
                ) : (
                  sessions.map((s) => (
                    <tr key={s.jti}>
                      <td style={{ fontFamily: "monospace", fontSize: 11.5 }}>{s.jti}</td>
                      <td>{new Date(s.created_at).toLocaleString()}</td>
                      <td>{new Date(s.expires_at).toLocaleString()}</td>
                      <td>
                        <span className={`qx-badge ${s.is_live ? "active" : "rejected"}`}>{s.is_live ? "live" : "revoked"}</span>
                      </td>
                      <td>
                        {s.is_live && (
                          <button className="qx-btn qx-btn-sm" disabled={busy === s.jti} onClick={() => revokeSession(s.jti)}>
                            {busy === s.jti ? "Revoking…" : "Revoke"}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {sessions.some((s) => s.is_live) && (
            <button className="qx-btn qx-btn-sm" style={{ marginTop: 10 }} disabled={busy === "all"} onClick={revokeAll}>
              {busy === "all" ? "Revoking all…" : "Revoke All Sessions For This User"}
            </button>
          )}
        </>
      )}
    </AppShell>
  );
}
