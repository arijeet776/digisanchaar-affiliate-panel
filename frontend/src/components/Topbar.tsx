import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { IconLogout, IconMenu, IconNotifications } from "./Icons";
import { ThemeToggle } from "./ThemeToggle";

export function Topbar({ title, onMenuClick }: { title: string; onMenuClick: () => void }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  const [unread, setUnread] = useState(false);
  useEffect(() => {
    if (!user) return;
    const check = () => {
      api.get<{ items: { id: string }[] }>("/announcements")
        .then((r) => {
          let seen: string | null = null;
          try { seen = localStorage.getItem("qx_seen_announcement"); } catch { /* storage unavailable */ }
          setUnread(!!r.data.items[0] && r.data.items[0].id !== seen && user.role !== "super_admin");
        })
        .catch(() => undefined);
    };
    check();
    window.addEventListener("qx-announcements-seen", check);
    return () => window.removeEventListener("qx-announcements-seen", check);
  }, [user]);

  const initial = user?.role ? user.role.charAt(0).toUpperCase() : "?";

  return (
    <header className="qx-topbar" aria-label="Top bar">
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button className="qx-icon-btn qx-menu-btn" onClick={onMenuClick} aria-label="Open navigation menu">
          <IconMenu width={16} height={16} />
        </button>
        <span className="qx-topbar-title">{title}</span>
      </div>
      <div className="qx-topbar-actions">
        <ThemeToggle />
        <button className="qx-icon-btn" aria-label="Notifications" onClick={() => navigate("/notifications")}>
          <IconNotifications width={16} height={16} />
          {unread && <span className="qx-bell-dot" aria-label="New message" />}
        </button>
        <span className="qx-avatar" title={user?.role} role="img" aria-label={`Signed in as ${user?.role ?? "user"}`}>
          {initial}
        </span>
        <button className="qx-icon-btn" aria-label="Log out" onClick={handleLogout}>
          <IconLogout width={16} height={16} />
        </button>
      </div>
    </header>
  );
}
