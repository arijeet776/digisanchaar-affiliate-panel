import { useCallback, useState, type ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

const COLLAPSE_KEY = "qx.sidebar.collapsed";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false; // storage can be blocked; the sidebar then simply starts expanded
  }
}

export function AppShell({ title, children }: { title: string; children: ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((c) => {
      const next = !c;
      try {
        window.localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  return (
    <div className={`qx-app${collapsed ? " qx-sidebar-collapsed" : ""}`}>
      <a href="#main-content" className="qx-skip-link">Skip to main content</a>
      <Sidebar open={drawerOpen} onClose={() => setDrawerOpen(false)} collapsed={collapsed} onToggleCollapse={toggleCollapsed} />
      <div className="qx-main">
        <Topbar title={title} onMenuClick={() => setDrawerOpen(true)} />
        <main className="qx-content" id="main-content" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
