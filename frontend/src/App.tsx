import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ProtectedRoute, roleHome } from "./auth/ProtectedRoute";
import { ThemeProvider } from "./theme/ThemeContext";
import { AccentProvider } from "./theme/AccentContext";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ManagersPage } from "./pages/ManagersPage";
import { ManagerDetailPage } from "./pages/ManagerDetailPage";
import { PublishersPage } from "./pages/PublishersPage";
import { PublisherDetailPage } from "./pages/PublisherDetailPage";
import { CampaignsPage } from "./pages/CampaignsPage";
import { CampaignCreatePage } from "./pages/CampaignCreatePage";
import { CampaignDetailPage } from "./pages/CampaignDetailPage";
import { CampaignEditPage } from "./pages/CampaignEditPage";
import { TrackingLinksPage } from "./pages/TrackingLinksPage";
import { ReportsPage } from "./pages/ReportsPage";
import { FinancialsPage } from "./pages/FinancialsPage";
import { SecurityOpsPage } from "./pages/SecurityOpsPage";
import { AccessRequestsPage } from "./pages/AccessRequestsPage";
import { ConversionReviewPage } from "./pages/ConversionReviewPage";
import { ClickReportPage } from "./pages/ClickReportPage";
import { OfflineReportPage } from "./pages/OfflineReportPage";
import { PublisherCampaignDetailPage } from "./pages/publisher/PublisherCampaignDetailPage";
import { PublisherBrowsePage } from "./pages/publisher/PublisherBrowsePage";
import { PublisherReportsPage } from "./pages/publisher/PublisherReportsPage";
import { PublisherSettlementsPage } from "./pages/publisher/PublisherSettlementsPage";
import { IntegrationsPage } from "./pages/IntegrationsPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { AuditLogsPage } from "./pages/AuditLogsPage";
import { FraudPage } from "./pages/FraudPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SupportPage } from "./pages/SupportPage";
import { ProfilePage } from "./pages/ProfilePage";
import { ManagerDashboardPage } from "./pages/manager/ManagerDashboardPage";
import { ManagerPublishersPage } from "./pages/manager/ManagerPublishersPage";
import { ManagerCampaignsPage } from "./pages/manager/ManagerCampaignsPage";
import { ManagerCampaignDetailPage } from "./pages/manager/ManagerCampaignDetailPage";
import { ManagerReportsPage } from "./pages/manager/ManagerReportsPage";
import { ManagerFinancialsPage } from "./pages/manager/ManagerFinancialsPage";
import { PublisherHomePage } from "./pages/PublisherHomePage";
import { PublisherCampaignsPage } from "./pages/publisher/PublisherCampaignsPage";
import { PublisherPostbackPage } from "./pages/publisher/PublisherPostbackPage";
import { PublisherWalletPage } from "./pages/publisher/PublisherWalletPage";

const SUPER_ADMIN = ["super_admin"];
const MANAGER = ["manager"];

function Protected({ children, roles }: { children: React.ReactNode; roles?: string[] }) {
  return <ProtectedRoute roles={roles}>{children}</ProtectedRoute>;
}

function HomeRedirect() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "var(--text-secondary)" }}>
        Loading…
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={roleHome(user.role)} replace />;
}

export default function App() {
  return (
    <ThemeProvider>
      <AccentProvider>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/register/:token" element={<RegisterPage />} />
          {/* legacy invite links (pre-16.2.1) */}
          <Route path="/onboarding/publisher" element={<RegisterPage />} />
          <Route path="/onboarding/manager" element={<RegisterPage />} />

          {/* Super Admin panel */}
          <Route path="/dashboard" element={<Protected roles={SUPER_ADMIN}><DashboardPage /></Protected>} />
          <Route path="/managers" element={<Protected roles={SUPER_ADMIN}><ManagersPage /></Protected>} />
          <Route path="/managers/:userId" element={<Protected roles={SUPER_ADMIN}><ManagerDetailPage /></Protected>} />
          <Route path="/publishers" element={<Protected roles={SUPER_ADMIN}><PublishersPage /></Protected>} />
          <Route path="/publishers/:userId" element={<Protected roles={SUPER_ADMIN}><PublisherDetailPage /></Protected>} />
          <Route path="/campaigns" element={<Protected roles={SUPER_ADMIN}><CampaignsPage /></Protected>} />
          <Route path="/campaigns/new" element={<Protected roles={SUPER_ADMIN}><CampaignCreatePage /></Protected>} />
          <Route path="/campaigns/:campaignId" element={<Protected roles={SUPER_ADMIN}><CampaignDetailPage /></Protected>} />
          <Route path="/campaigns/:campaignId/edit" element={<Protected roles={SUPER_ADMIN}><CampaignEditPage /></Protected>} />
          <Route path="/tracking-links" element={<Protected roles={SUPER_ADMIN}><TrackingLinksPage /></Protected>} />
          <Route path="/reports" element={<Protected roles={SUPER_ADMIN}><ReportsPage /></Protected>} />
          <Route path="/financials" element={<Protected roles={SUPER_ADMIN}><FinancialsPage /></Protected>} />
          <Route path="/access-requests" element={<Protected roles={SUPER_ADMIN}><AccessRequestsPage /></Protected>} />
          <Route path="/conversion-review" element={<Protected roles={SUPER_ADMIN}><ConversionReviewPage /></Protected>} />
          <Route path="/click-report" element={<Protected roles={SUPER_ADMIN}><ClickReportPage /></Protected>} />
          <Route path="/offline-report" element={<Protected roles={SUPER_ADMIN}><OfflineReportPage /></Protected>} />
          <Route path="/manager/click-report" element={<Protected roles={MANAGER}><ClickReportPage /></Protected>} />
          <Route path="/manager/offline-report" element={<Protected roles={MANAGER}><OfflineReportPage /></Protected>} />
          <Route path="/publisher/click-report" element={<Protected roles={["publisher"]}><ClickReportPage /></Protected>} />
          <Route path="/manager/access-requests" element={<Protected roles={MANAGER}><AccessRequestsPage /></Protected>} />
          <Route path="/manager/conversion-review" element={<Protected roles={MANAGER}><ConversionReviewPage /></Protected>} />
          <Route path="/publisher/campaigns/:campaignId" element={<Protected roles={["publisher"]}><PublisherCampaignDetailPage /></Protected>} />
          <Route path="/publisher/browse" element={<Protected roles={["publisher"]}><PublisherBrowsePage /></Protected>} />
          <Route path="/security" element={<Protected roles={SUPER_ADMIN}><SecurityOpsPage /></Protected>} />
          <Route path="/integrations" element={<Protected roles={SUPER_ADMIN}><IntegrationsPage /></Protected>} />
          <Route path="/audit-logs" element={<Protected roles={SUPER_ADMIN}><AuditLogsPage /></Protected>} />
          <Route path="/fraud" element={<Protected roles={SUPER_ADMIN}><FraudPage /></Protected>} />
          <Route path="/settings" element={<Protected roles={SUPER_ADMIN}><SettingsPage /></Protected>} />

          {/* Manager panel */}
          <Route path="/manager/dashboard" element={<Protected roles={MANAGER}><ManagerDashboardPage /></Protected>} />
          <Route path="/manager/publishers" element={<Protected roles={MANAGER}><ManagerPublishersPage /></Protected>} />
          <Route path="/manager/campaigns" element={<Protected roles={MANAGER}><ManagerCampaignsPage /></Protected>} />
          <Route path="/manager/campaigns/:campaignId" element={<Protected roles={MANAGER}><ManagerCampaignDetailPage /></Protected>} />
          <Route path="/manager/reports" element={<Protected roles={MANAGER}><ManagerReportsPage /></Protected>} />
          <Route path="/manager/financials" element={<Protected roles={MANAGER}><ManagerFinancialsPage /></Protected>} />

          {/* Publisher panel */}
          <Route path="/publisher/home" element={<Protected roles={["publisher"]}><PublisherHomePage /></Protected>} />
          <Route path="/publisher/campaigns" element={<Protected roles={["publisher"]}><PublisherCampaignsPage /></Protected>} />
          <Route path="/publisher/postback" element={<Protected roles={["publisher"]}><PublisherPostbackPage /></Protected>} />
          <Route path="/publisher/wallet" element={<Protected roles={["publisher"]}><PublisherWalletPage /></Protected>} />
          <Route path="/publisher/reports" element={<Protected roles={["publisher"]}><PublisherReportsPage /></Protected>} />
          <Route path="/publisher/settlements" element={<Protected roles={["publisher"]}><PublisherSettlementsPage /></Protected>} />

          {/* Shared authenticated pages */}
          <Route path="/notifications" element={<Protected><NotificationsPage /></Protected>} />
          <Route path="/support" element={<Protected><SupportPage /></Protected>} />
          <Route path="/profile" element={<Protected><ProfilePage /></Protected>} />

          <Route path="/" element={<HomeRedirect />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </AuthProvider>
      </AccentProvider>
    </ThemeProvider>
  );
}

function NotFound() {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 18, fontWeight: 700 }}>404</div>
      <div style={{ color: "var(--text-secondary)", fontSize: 13 }}>This page doesn't exist.</div>
      <a href="/" style={{ fontSize: 13 }} data-testid="notfound-home">Go to home</a>
    </div>
  );
}
