import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { IconBuilding, IconCalendar, IconMail, IconPhone, IconShield, IconUsers } from "../components/Icons";
import { useAuth } from "../auth/AuthContext";
import { AppShell } from "../components/AppShell";
import { StatusBadge } from "../components/Common";
import { SuccessPopup } from "../components/SuccessPopup";

interface PubProfile {
  publisher_id: string; display_name: string; email: string | null; email_verified: boolean;
  account_status: string | null; mobile: string | null; company: string | null; member_since: string | null;
  assigned_manager_name?: string | null;
}

function PublisherProfile({ onLogout }: { onLogout: () => void }) {
  const [p, setP] = useState<PubProfile | null>(null);
  useEffect(() => { api.get<PubProfile>("/publisher/profile").then((r) => setP(r.data)).catch(() => undefined); }, []);
  if (!p) return <AppShell title="Account"><div className="qx-empty-state">Loading…</div></AppShell>;
  const initials = p.display_name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  const active = (p.account_status ?? "").toLowerCase() === "active";
  return (
    <AppShell title="Account">
      <div className="qx-eyebrow-pill"><IconShield width={14} height={14} /> ACCOUNT SETTINGS</div>
      <div className="qx-page-title qx-page-title-xl" style={{ fontSize: 40 }}>Account Profile</div>
      <div className="qx-page-subtitle" style={{ marginBottom: 14 }}>Manage your affiliate profile settings, contact information, and verification status.</div>
      <div className="qx-info-label">ACCOUNT STATUS</div>
      <div style={{ fontWeight: 700, color: active ? "var(--qx-success)" : "var(--text-secondary)", marginBottom: 18, textTransform: "uppercase" }}>{p.account_status ?? "—"}</div>

      <div className="qx-profile-hero">
        <div className="qx-profile-avatar">{initials}</div>
        <div className="qx-profile-name">{p.display_name}</div>
        <div className="qx-idpill">AFFILIATE ID: <b style={{ color: "var(--text-primary)" }}>{p.publisher_id}</b></div>
      </div>

      <div className="qx-detail-card">
        <span className={`qx-badge-corner ${p.email_verified ? "good" : "bad"}`}>{p.email_verified ? "VERIFIED" : "UNVERIFIED"}</span>
        <div className="ic"><IconMail width={22} height={22} /></div>
        <div className="qx-detail-label">Email Address</div>
        <div className="qx-detail-value" style={{ fontFamily: "ui-monospace, monospace", fontSize: 19 }}>{p.email ?? "—"}</div>
        <div className="qx-csub">Your registered email address</div>
      </div>
      <div className="qx-detail-card">
        <div className="ic"><IconPhone width={22} height={22} /></div>
        <div className="qx-detail-label">Phone Number</div>
        <div className="qx-detail-value">{p.mobile ?? "—"}</div>
        <div className="qx-csub">Your primary contact number</div>
      </div>
      <div className="qx-detail-card">
        <div className="ic"><IconBuilding width={22} height={22} /></div>
        <div className="qx-detail-label">Company / Agency</div>
        <div className="qx-detail-value">{p.company ?? "—"}</div>
        <div className="qx-csub">Associated company or agency name</div>
      </div>
      <div className="qx-detail-card">
        <div className="ic"><IconCalendar width={22} height={22} /></div>
        <div className="qx-detail-label">Member Since</div>
        <div className="qx-detail-value" style={{ fontFamily: "ui-monospace, monospace" }}>{p.member_since ? new Date(p.member_since).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" }) : "—"}</div>
        <div className="qx-csub">Date you joined the platform</div>
      </div>

      <div className="qx-detail-card">
        <div className="ic"><IconUsers width={22} height={22} /></div>
        <div className="qx-detail-label">Assigned Manager</div>
        <div className="qx-detail-value">{p.assigned_manager_name ?? "Not assigned yet"}</div>
        <div className="qx-csub">Your account manager for this network</div>
      </div>

      <div className="qx-panel" style={{ padding: 24 }}>
        <div className="qx-detail-label" style={{ display: "flex", justifyContent: "space-between" }}>VERIFICATION <IconShield width={18} height={18} style={{ color: "var(--qx-accent)" }} /></div>
        <div className="qx-page-title" style={{ marginBottom: 16 }}>Status Overview</div>
        <div className="qx-verified">
          <div className="qx-detail-label" style={{ color: "#10b981" }}>VERIFICATION LEVEL</div>
          <div className="big">{active ? "VERIFIED" : "PENDING"}</div>
          <div className="qx-csub">{active ? "Full access to campaigns and payouts" : "Access unlocks once your account is approved"}</div>
        </div>
        <div className="qx-csub" style={{ textAlign: "center", marginTop: 14, fontStyle: "italic" }}>Your information is securely encrypted and protected.</div>
      </div>
      <button className="qx-btn qx-btn-danger" onClick={onLogout}>Log out</button>
    </AppShell>
  );
}

function ManagerContact() {
  const [mobile, setMobile] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.get<{ display_name: string; mobile: string | null }>("/manager/me")
      .then((r) => { setMobile(r.data.mobile ?? ""); setSaved(r.data.mobile); }).catch(() => undefined);
  }, []);
  async function save() {
    setError(null); setMsg(null);
    try {
      const r = await api.put<{ mobile: string | null }>("/manager/me/mobile", { mobile: mobile.trim() });
      setSaved(r.data.mobile); setMsg("Mobile number saved.");
    } catch (e) { setError(e instanceof ApiError ? e.message : "Failed to save"); }
  }
  return (
    <div className="qx-card" style={{ maxWidth: 480, marginTop: 16 }} data-testid="manager-contact">
      <div style={{ fontWeight: 700 }}>Contact number</div>
      <div className="qx-hint">Shown to the Publishers assigned to you under Support &amp; Help.</div>
      {error && <div className="qx-error-banner" role="alert" style={{ marginTop: 10 }}>{error}</div>}
      <SuccessPopup open={!!msg && !error} onClose={() => setMsg(null)} title="Saved">{msg}</SuccessPopup>
      <div className="qx-field" style={{ marginTop: 12 }}>
        <label htmlFor="mgr-mobile">Mobile number</label>
        <input id="mgr-mobile" className="qx-input" type="tel" value={mobile} onChange={(e) => setMobile(e.target.value)} data-testid="manager-mobile-input" />
      </div>
      <button className="qx-btn qx-btn-primary" disabled={!mobile.trim() || mobile.trim() === saved} onClick={save} data-testid="manager-mobile-save">Save</button>
    </div>
  );
}

export function ProfilePage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  if (!user) return null;
  if (user.role === "publisher") return <PublisherProfile onLogout={handleLogout} />;

  return (
    <AppShell title="Profile">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Profile &amp; Account</div>
          <div className="qx-page-subtitle">Account-level details, read fresh from the server on every session.</div>
        </div>
      </div>

      <div className="qx-card" style={{ maxWidth: 480 }}>
        <div className="qx-row">
          <div>
            <div className="qx-kpi-label">Role</div>
            <div style={{ textTransform: "capitalize" }}>{user.role.replace(/_/g, " ")}</div>
          </div>
          <div>
            <div className="qx-kpi-label">Account status</div>
            <StatusBadge status={user.account_status} />
          </div>
        </div>
        <div style={{ marginTop: 14 }}>
          <div className="qx-kpi-label">User ID</div>
          <div style={{ fontFamily: "monospace", fontSize: 12.5 }}>{user.user_id}</div>
        </div>
        <button className="qx-btn qx-btn-danger" style={{ marginTop: 20 }} onClick={handleLogout}>
          Log out
        </button>
      </div>
      {user.role === "manager" && <ManagerContact />}
    </AppShell>
  );
}
