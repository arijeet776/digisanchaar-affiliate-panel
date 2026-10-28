import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import {
  IconDashboard, IconUsers, IconManager, IconCampaign, IconLink, IconReports,
  IconFinancial, IconIntegrations, IconNotifications, IconSettings, IconAudit,
  IconSupport, IconProfile, IconShield, IconChevronRight, IconChevronLeft, IconPhone,
} from "./Icons";

type LeafItem = { to: string; label: string; icon: React.FC<React.SVGProps<SVGSVGElement>> };
type GroupItem = { label: string; icon: React.FC<React.SVGProps<SVGSVGElement>>; children: { to: string; label: string }[] };
type NavItem = LeafItem | GroupItem;
const isGroup = (i: NavItem): i is GroupItem => "children" in i;

const NAV_SECTIONS: { label: string; items: NavItem[] }[] = [
  {
    label: "Overview",
    items: [{ to: "/dashboard", label: "Dashboard", icon: IconDashboard }],
  },
  {
    label: "User Management",
    items: [
      { to: "/managers", label: "Managers", icon: IconManager },
      { to: "/publishers", label: "Publishers", icon: IconUsers },
    ],
  },
  {
    label: "Network",
    items: [
      { to: "/campaigns", label: "Campaigns", icon: IconCampaign },
      { to: "/access-requests", label: "Access Requests", icon: IconUsers },
      { to: "/conversion-review", label: "Conversion Review", icon: IconAudit },
      { to: "/tracking-links", label: "Tracking Links", icon: IconLink },
      { to: "/reports", label: "Reports", icon: IconReports },
      { to: "/click-report", label: "Click Report", icon: IconReports },
      { to: "/offline-report", label: "Offline Report", icon: IconAudit },
      { to: "/financials", label: "Financials", icon: IconFinancial },
      { to: "/integrations", label: "Integrations", icon: IconIntegrations },
    ],
  },
  {
    label: "System",
    items: [
      { to: "/audit-logs", label: "Audit Logs", icon: IconAudit },
      { to: "/security", label: "Security & Sessions", icon: IconShield },
      { to: "/fraud", label: "Fraud & Security", icon: IconShield },
      { to: "/notifications", label: "Notifications", icon: IconNotifications },
      { to: "/settings", label: "System Settings", icon: IconSettings },
      { to: "/support", label: "Support & Help", icon: IconSupport },
    ],
  },
  {
    label: "Account",
    items: [{ to: "/profile", label: "Profile", icon: IconProfile }],
  },
];

const MANAGER_NAV_SECTIONS: { label: string; items: NavItem[] }[] = [
  {
    label: "Overview",
    items: [{ to: "/manager/dashboard", label: "Dashboard", icon: IconDashboard }],
  },
  {
    label: "My Network",
    items: [
      { to: "/manager/publishers", label: "My Publishers", icon: IconUsers },
      { to: "/manager/campaigns", label: "Campaigns", icon: IconCampaign },
      { to: "/manager/access-requests", label: "Access Requests", icon: IconUsers },
      { to: "/manager/conversion-review", label: "Conversion Review", icon: IconAudit },
      { to: "/manager/reports", label: "Reports", icon: IconReports },
      { to: "/manager/click-report", label: "Click Report", icon: IconReports },
      { to: "/manager/offline-report", label: "Offline Report", icon: IconAudit },
      { to: "/manager/financials", label: "Financials", icon: IconFinancial },
    ],
  },
  {
    label: "Account",
    items: [
      { to: "/profile", label: "Profile", icon: IconProfile },
      { to: "/support", label: "Support & Help", icon: IconSupport },
    ],
  },
];

// Publisher: Dashboard, Campaign (All / Approved), Report (six sub-reports,
// Event Report intentionally excluded), Account (Profile / Wallet / Postback
// Settings), Settlements, Support & Help.
const PUBLISHER_NAV_SECTIONS: { label: string; items: NavItem[] }[] = [
  {
    label: "Main Menu",
    items: [
      { to: "/publisher/home", label: "Dashboard", icon: IconDashboard },
      {
        label: "Campaigns", icon: IconCampaign,
        children: [
          { to: "/publisher/browse", label: "All Campaigns" },
          { to: "/publisher/campaigns", label: "Approved Campaigns" },
        ],
      },
      {
        label: "Reports", icon: IconReports,
        children: [
          { to: "/publisher/reports?tab=conversion", label: "Conversion Report" },
          { to: "/publisher/reports?tab=clicks", label: "Clicks Report" },
          { to: "/publisher/reports?tab=campaign", label: "Campaign Report" },
          { to: "/publisher/reports?tab=export", label: "Export Center" },
          { to: "/publisher/reports?tab=postback", label: "Postback Logs" },
          { to: "/publisher/reports?tab=performance", label: "Performance Report" },
        ],
      },
      {
        label: "Account", icon: IconProfile,
        children: [
          { to: "/profile", label: "Profile" },
          { to: "/publisher/wallet", label: "Wallet" },
          { to: "/publisher/postback", label: "Postback Settings" },
        ],
      },
      { to: "/publisher/settlements", label: "Settlements", icon: IconFinancial },
    ],
  },
];

function GroupNav({ item, onNavigate, collapsed, onExpand }: { item: GroupItem; onNavigate: () => void; collapsed: boolean; onExpand: () => void }) {
  const location = useLocation();
  const containsCurrent = item.children.some((c) => location.pathname + location.search === c.to || location.pathname === c.to.split("?")[0]);
  const [open, setOpen] = useState(containsCurrent);
  const GroupIcon = item.icon;

  return (
    <div>
      <button type="button" className={`qx-nav-group-btn${open ? " open" : ""}`} title={collapsed ? item.label : undefined}
        onClick={() => { if (collapsed) { onExpand(); setOpen(true); } else setOpen((o) => !o); }} aria-expanded={open && !collapsed} aria-label={collapsed ? item.label : undefined}>
        <GroupIcon width={16} height={16} />
        <span className="qx-nav-text">{item.label}</span>
        <IconChevronRight width={13} height={13} className={`qx-nav-group-chevron${open ? " open" : ""}`} />
      </button>
      {open && !collapsed && (
        <div className="qx-nav-subitems">
          {item.children.map((c) => {
            const [pathname, search] = c.to.split("?");
            const active = location.pathname === pathname && (!search || location.search.includes(search));
            return (
              <Link key={c.to} to={c.to} onClick={onNavigate} className={`qx-nav-sublink${active ? " active" : ""}`} aria-current={active ? "page" : undefined}>
                {c.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

const NARROW_QUERY = "(max-width: 880px)";

/** True on phones/tablets where the sidebar is a slide-in drawer instead of a docked column. */
function useIsNarrow(): boolean {
  const [narrow, setNarrow] = useState<boolean>(() => typeof window !== "undefined" && window.matchMedia(NARROW_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(NARROW_QUERY);
    const update = () => setNarrow(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return narrow;
}

export function Sidebar({ open, onClose, collapsed: collapsedProp = false, onToggleCollapse }: { open: boolean; onClose: () => void; collapsed?: boolean; onToggleCollapse?: () => void }) {
  const { user } = useAuth();
  const isNarrow = useIsNarrow();
  // The saved "collapsed" flag only applies to the docked desktop sidebar. In the drawer it must
  // never hide labels or sub-menus, and the arrow there simply closes the drawer.
  const collapsed = collapsedProp && !isNarrow;
  const onArrowClick = () => (isNarrow ? onClose() : onToggleCollapse?.());
  const sections =
    user?.role === "manager"
      ? MANAGER_NAV_SECTIONS
      : user?.role === "publisher"
        ? PUBLISHER_NAV_SECTIONS
        : NAV_SECTIONS;
  const [amName, setAmName] = useState<string | null>(null);
  const [pubName, setPubName] = useState<string | null>(null);
  useEffect(() => {
    if (user?.role !== "publisher") return;
    api.get<{ name: string | null }>("/publisher/account-manager").then((r) => setAmName(r.data.name)).catch(() => undefined);
    api.get<{ display_name: string }>("/publisher/profile").then((r) => setPubName(r.data.display_name)).catch(() => undefined);
  }, [user?.role]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  const roleLabel = pubName ?? (user?.role ? user.role.replace(/_/g, " ") : "account");
  const initial = (pubName ?? user?.role ?? "?").charAt(0).toUpperCase();

  return (
    <>
      <div className={`qx-sidebar-backdrop ${open ? "open" : ""}`} onClick={onClose} aria-hidden="true" />
      <aside className={`qx-sidebar ${open ? "open" : ""}${collapsed ? " collapsed" : ""}${user?.role === "publisher" ? " qx-sidebar-pub" : ""}`} data-testid="sidebar" aria-label="Sidebar">
        <div className="qx-sidebar-brand">
          {/* Same logo as the login/register page; light/dark variant follows <html data-theme> in CSS. */}
          <span className="qx-sidebar-logo-wrap">
            <img src="/quantix-logo-full.png" alt="DigiSanchaar" className="qx-sidebar-logo qx-brand-light" />
            <img src="/quantix-logo-full-dark.png" alt="" aria-hidden="true" className="qx-sidebar-logo qx-brand-dark" />
          </span>
          <img src="/quantix-logo-mark.png" alt="DigiSanchaar" className="qx-sidebar-brand-mark" />
          {onToggleCollapse && (
            <button type="button" className="qx-icon-btn qx-collapse-btn" onClick={onArrowClick} data-testid="sidebar-collapse-toggle"
              aria-label={isNarrow ? "Close menu" : collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-pressed={isNarrow ? undefined : collapsed} title={isNarrow ? "Close menu" : collapsed ? "Expand sidebar" : "Collapse sidebar"}>
              {collapsed ? <IconChevronRight width={15} height={15} /> : <IconChevronLeft width={15} height={15} />}
            </button>
          )}
        </div>

        <nav aria-label="Main navigation">
        {sections.map((section) => (
          <div className="qx-nav-section" key={section.label}>
            <div className="qx-nav-label">{section.label}</div>
            {section.items.map((item) =>
              isGroup(item) ? (
                <GroupNav key={item.label} item={item} onNavigate={onClose} collapsed={collapsed} onExpand={() => onToggleCollapse?.()} />
              ) : (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={onClose}
                  className={({ isActive }) => `qx-nav-link${isActive ? " active" : ""}`}
                  data-testid={`nav-${item.to.replace(/\//g, "").replace(/^$/, "home")}`}
                  title={collapsed ? item.label : undefined}
                  aria-label={collapsed ? item.label : undefined}
                >
                  <item.icon width={16} height={16} />
                  <span className="qx-nav-text">{item.label}</span>
                </NavLink>
              )
            )}
          </div>
        ))}
        </nav>

        {user?.role === "publisher" && (
          <div className="qx-support-card">
            <div className="hd"><IconSupport width={15} height={15} /> SUPPORT &amp; HELP</div>
            {amName && <Link to="/support" onClick={onClose} className="qx-support-link am"><IconProfile width={15} height={15} /> AM: {amName}</Link>}
            <Link to="/support" onClick={onClose} className="qx-support-link"><IconPhone width={15} height={15} /> Contact Support</Link>
          </div>
        )}

        <div className="qx-sidebar-footer">
          <Link to="/profile" className="qx-user-card" onClick={onClose} data-testid="sidebar-user-card">
            <span className="qx-user-avatar">
              {initial}
              <span className="qx-user-online" />
            </span>
            <span className="qx-user-meta">
              <span className="qx-user-name">{roleLabel}</span>
              <span className="qx-user-role">Signed in</span>
            </span>
            <IconChevronRight width={14} height={14} />
          </Link>
        </div>
      </aside>
    </>
  );
}
