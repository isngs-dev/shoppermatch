import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AdminLayout } from "./components/Layout";
import { Loading } from "./components/ui";
import { useAuth } from "./lib/auth";
import { AuditLogs } from "./pages/AuditLogs";
import { Campaigns } from "./pages/Campaigns";
import { Dashboard } from "./pages/Dashboard";
import { Home } from "./pages/Home";
import { Insights } from "./pages/Insights";
import { Integrations } from "./pages/Integrations";
import { Login } from "./pages/Login";
import { Outreach } from "./pages/Outreach";
import { Recommendations } from "./pages/Recommendations";
import { Settings } from "./pages/Settings";
import { ShopperInvite } from "./pages/ShopperInvite";
import { Shoppers } from "./pages/Shoppers";
import { Shops } from "./pages/Shops";
import { Tracking } from "./pages/Tracking";

function RequireAuth({ children }: { children: ReactNode }) {
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
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<Login />} />
      <Route path="/shop/:token" element={<ShopperInvite />} />

      {/* Admin (authenticated) */}
      <Route
        element={
          <RequireAuth>
            <AdminLayout />
          </RequireAuth>
        }
      >
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/campaigns" element={<Navigate to="/campaigns/active" replace />} />
        <Route path="/campaigns/:param" element={<Campaigns />} />
        <Route path="/shops" element={<Shops />} />
        <Route path="/shoppers" element={<Shoppers />} />
        <Route path="/recommendations" element={<Recommendations />} />
        <Route path="/outreach" element={<Outreach />} />
        <Route path="/tracking" element={<Tracking />} />
        <Route path="/insights" element={<Insights />} />
        <Route path="/audit-logs" element={<AuditLogs />} />
        <Route path="/integrations" element={<Integrations />} />
        <Route path="/settings" element={<Settings />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
