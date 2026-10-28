import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function roleHome(role?: string): string {
  if (role === "manager") return "/manager/dashboard";
  if (role === "publisher") return "/publisher/home";
  return "/dashboard";
}

/**
 * UX convenience only — it stops an obviously-wrong role from seeing a flash
 * of another panel's UI before API calls 403. It is NOT the security
 * boundary: every endpoint re-checks role/status/scope from the database on
 * every request (see backend/app/core/rbac.py). A client bypassing this
 * component entirely would still get 401/403 from the API.
 */
export function ProtectedRoute({ children, roles }: { children: React.ReactNode; roles?: string[] }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "var(--text-secondary)" }}>
        Loading…
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (roles && !roles.includes(user.role)) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", flexDirection: "column", gap: 8 }} data-testid="access-restricted">
        <div style={{ fontSize: 16, fontWeight: 600 }}>Access restricted</div>
        <div style={{ color: "var(--text-secondary)", fontSize: 13 }}>
          This area is not available to your account role.
        </div>
        <Navigate to={roleHome(user.role)} replace />
      </div>
    );
  }

  return <>{children}</>;
}
