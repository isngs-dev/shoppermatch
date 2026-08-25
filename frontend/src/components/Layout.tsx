import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { classNames } from "../lib/format";
import { useTheme } from "../lib/theme";
import {
  IconClipboard,
  IconDashboard,
  IconHistory,
  IconLightbulb,
  IconLogout,
  IconMenu,
  IconMoon,
  IconPlug,
  IconSettings,
  IconSun,
  IconTarget,
  IconUsers,
  IconX,
} from "./Icons";
import { NotificationsBell } from "./NotificationsBell";
import { Avatar, Logo } from "./ui";
import { VoiceAssistant } from "./VoiceAssistant";

type NavItem = { to: string; label: string; icon: (p: any) => ReactNode };

// Campaigns/Shops/Shoppers/Recommendations/Outreach + their AI features now
// live exclusively in the Client Portal — ISN Admin keeps system-level
// oversight only (monitoring, attribution, integrations, audit).
const PRIMARY: NavItem[] = [
  { to: "/admin/dashboard", label: "Dashboard", icon: IconDashboard },
  { to: "/admin/tracking", label: "Tracking", icon: IconTarget },
];
const SECONDARY: NavItem[] = [
  { to: "/admin/insights", label: "Insights", icon: IconLightbulb },
  { to: "/admin/users", label: "Users", icon: IconUsers },
  { to: "/admin/client-activity", label: "Client Activity", icon: IconHistory },
  { to: "/admin/audit-logs", label: "Audit Logs", icon: IconClipboard },
  { to: "/admin/integrations", label: "Integrations", icon: IconPlug },
  { to: "/admin/settings", label: "Settings", icon: IconSettings },
];

const ALL_NAV = [...PRIMARY, ...SECONDARY];

function titleFor(pathname: string): string {
  const match = ALL_NAV.find((n) => pathname === n.to || pathname.startsWith(n.to + "/"));
  return match?.label || "Dashboard";
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    classNames(
      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
      isActive
        ? "bg-brand-600 text-white"
        : "text-slate-300 hover:bg-slate-800 hover:text-white"
    );
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center px-5">
        <Logo />
        <span className="ml-auto rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-semibold text-slate-400">
          ISN
        </span>
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
        {PRIMARY.map((n) => (
          <NavLink key={n.to} to={n.to} className={linkClass} onClick={onNavigate}>
            <n.icon width={18} height={18} />
            {n.label}
          </NavLink>
        ))}
        <div className="px-3 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          Platform
        </div>
        {SECONDARY.map((n) => (
          <NavLink key={n.to} to={n.to} className={linkClass} onClick={onNavigate}>
            <n.icon width={18} height={18} />
            {n.label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-slate-800 p-3 text-[11px] text-slate-500">
        AI-powered shopper outreach & attribution
      </div>
    </div>
  );
}

export function AdminLayout() {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const title = titleFor(location.pathname);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 bg-slate-900 md:block">
        <SidebarContent />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 bg-slate-900">
            <button
              className="absolute right-3 top-4 text-slate-400 hover:text-white"
              onClick={() => setMobileOpen(false)}
            >
              <IconX />
            </button>
            <SidebarContent onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="md:pl-64">
        {/* Topbar */}
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-slate-200 bg-white/80 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80 sm:px-6">
          <button
            className="btn-ghost md:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open menu"
          >
            <IconMenu />
          </button>
          <h1 className="text-lg font-semibold text-slate-900 dark:text-white">{title}</h1>
          <div className="ml-auto flex items-center gap-2">
            <NotificationsBell />
            <button className="btn-ghost" onClick={toggle} aria-label="Toggle theme">
              {theme === "dark" ? <IconSun /> : <IconMoon />}
            </button>
            <div className="hidden items-center gap-2 sm:flex">
              <Avatar name={user?.name} className="h-8 w-8" />
              <div className="leading-tight">
                <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                  {user?.name}
                </div>
                <div className="text-[11px] text-slate-400">{user?.role}</div>
              </div>
            </div>
            <button className="btn-ghost" onClick={logout} aria-label="Log out" title="Log out">
              <IconLogout />
            </button>
          </div>
        </header>

        <main className="mx-auto max-w-7xl p-4 sm:p-6">
          <Outlet />
        </main>
      </div>

      <VoiceAssistant />
    </div>
  );
}
