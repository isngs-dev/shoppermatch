import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AdminLayout } from "./components/Layout";
import { ClientLayout } from "./components/ClientLayout";
import { Loading } from "./components/ui";
import { useAuth } from "./lib/auth";
import { AdminUsers } from "./pages/AdminUsers";
import { AuditLogs } from "./pages/AuditLogs";
import { Campaigns } from "./pages/Campaigns";
import { ClientActivity } from "./pages/ClientActivity";
import { Dashboard } from "./pages/Dashboard";
import { AutomationDetailPage } from "./pages/EmailAutomation";
import { ForgotPassword } from "./pages/ForgotPassword";
import { Home } from "./pages/Home";
import { Insights } from "./pages/Insights";
import { Integrations } from "./pages/Integrations";
import { Login } from "./pages/Login";
import { Outreach } from "./pages/Outreach";
import { Recommendations } from "./pages/Recommendations";
import { ResetPassword } from "./pages/ResetPassword";
import { Settings } from "./pages/Settings";
import { ShopperInvite } from "./pages/ShopperInvite";
import { SignUp } from "./pages/SignUp";
import { Shoppers } from "./pages/Shoppers";
import { Shops } from "./pages/Shops";
import { Tracking } from "./pages/Tracking";
import { ClientDashboard } from "./pages/client/ClientDashboard";
import { ClientInsights } from "./pages/client/ClientInsights";
import { ClientReports } from "./pages/client/ClientReports";
import { ClientProfile } from "./pages/client/ClientProfile";

function RequireRole({ role, children }: { role: "admin" | "client"; children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loading label="Checking session…" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  // Server-side enforcement already rejects the wrong role on every API call
  // (require_admin / require_client / require_operator in deps.py) — this
  // redirect is purely UX, not the security boundary.
  if (user.role !== role) {
    return <Navigate to={user.role === "admin" ? "/admin/dashboard" : "/client/dashboard"} replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<SignUp />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/shop/:token" element={<ShopperInvite />} />

      {/* ISN Admin Portal — system-level oversight: monitoring, attribution,
          integrations and audit, not day-to-day campaign operations (moved
          to the Client Portal). */}
      <Route
        element={
          <RequireRole role="admin">
            <AdminLayout />
          </RequireRole>
        }
      >
        <Route path="/admin/dashboard" element={<Dashboard />} />
        <Route path="/admin/tracking" element={<Tracking />} />
        <Route path="/admin/insights" element={<Insights />} />
        <Route path="/admin/users" element={<AdminUsers />} />
        <Route path="/admin/client-activity" element={<ClientActivity />} />
        <Route path="/admin/audit-logs" element={<AuditLogs />} />
        <Route path="/admin/integrations" element={<Integrations />} />
        <Route path="/admin/settings" element={<Settings />} />
      </Route>

      {/* Client Portal — full campaign operations: Campaigns, Shops,
          Shoppers, Recommendations, Outreach + every AI feature inside
          them. All server-side tenant-scoped to this client's own
          client_id (deps.py::require_operator + services/tenancy.py). */}
      <Route
        element={
          <RequireRole role="client">
            <ClientLayout />
          </RequireRole>
        }
      >
        <Route path="/client/dashboard" element={<ClientDashboard />} />
        <Route path="/client/campaigns" element={<Navigate to="/client/campaigns/active" replace />} />
        <Route path="/client/campaigns/:param" element={<Campaigns />} />
        <Route path="/client/shops" element={<Shops />} />
        <Route path="/client/shoppers" element={<Shoppers />} />
        <Route path="/client/recommendations" element={<Recommendations />} />
        <Route path="/client/outreach" element={<Outreach />} />
        <Route path="/client/outreach/automations/:automationId" element={<AutomationDetailPage />} />
        {/* Templates and Automation now live inside Outreach's tabs — these
            redirects keep old bookmarks/links working. */}
        <Route path="/client/email-templates" element={<Navigate to="/client/outreach?tab=templates" replace />} />
        <Route path="/client/email-automation" element={<Navigate to="/client/outreach?tab=batch" replace />} />
        <Route path="/client/insights" element={<ClientInsights />} />
        <Route path="/client/reports" element={<ClientReports />} />
        <Route path="/client/profile" element={<ClientProfile />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
