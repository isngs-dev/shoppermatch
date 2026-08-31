import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { classNames } from "../lib/format";
import { useTheme } from "../lib/theme";
import { IconLogout, IconMoon, IconSun } from "./Icons";
import { Avatar, Logo } from "./ui";
import { ClientVoiceAssistant } from "./ClientVoiceAssistant";

// Shops, Shoppers and Recommendations are deliberately not top-level nav
// items — they only make sense scoped to one campaign (active/upcoming/
// completed), so they live as tabs inside Campaign Detail instead of as
// a separate, campaign-less view here. Outreach (Send Invitation/Templates)
// follows the same logic: it only makes sense in the context of one
// campaign, so it's reached via each Campaign Detail's own Outreach tab
// rather than as a campaign-less top-level item. Email Automation is the
// one part of that page that isn't campaign-scoped (it runs sequences
// across shoppers/shops directly), so it keeps its own top-level entry.
const PRIMARY_NAV = [
  { to: "/client/dashboard", label: "Dashboard" },
  { to: "/client/campaigns", label: "Campaigns" },
  { to: "/client/email-automation", label: "Email Automation" },
  { to: "/client/insights", label: "Insights" },
  { to: "/client/reports", label: "Reports" },
];

// Deliberately a different shape from AdminLayout — a light top-nav SaaS
// shell instead of a dark data-dense sidebar, per the brief: "The Client
// should feel like a customer-facing SaaS portal, NOT an admin panel with
// buttons hidden."
export function ClientLayout() {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white dark:from-slate-950 dark:to-slate-950">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6">
          <Logo />
          <nav className="ml-2 hidden items-center gap-1 md:flex">
            {PRIMARY_NAV.map((n) => (
              <NavItem key={n.to} to={n.to} label={n.label} />
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <button className="btn-ghost" onClick={toggle} aria-label="Toggle theme">
              {theme === "dark" ? <IconSun /> : <IconMoon />}
            </button>
            {/* Profile & settings now live behind the account avatar itself,
                not as a top-nav tab — clicking it always goes to the
                logged-in client's own /client/profile (password change,
                org info, danger zone), never anyone else's. */}
            <NavLink
              to="/client/profile"
              className={({ isActive }) =>
                classNames(
                  "flex items-center gap-2 rounded-lg px-2 py-1.5 transition",
                  isActive ? "bg-brand-50 dark:bg-brand-950" : "hover:bg-slate-100 dark:hover:bg-slate-900"
                )
              }
              title="Profile & settings"
            >
              <Avatar name={user?.name} className="h-8 w-8" />
              <div className="hidden leading-tight sm:block">
                <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">{user?.name}</div>
                <div className="text-[11px] text-slate-400">{user?.client_name}</div>
              </div>
            </NavLink>
            <button className="btn-ghost" onClick={logout} aria-label="Log out" title="Log out">
              <IconLogout />
            </button>
          </div>
        </div>
        {/* Mobile nav row */}
        <nav className="flex gap-1 overflow-x-auto border-t border-slate-100 px-4 py-2 dark:border-slate-900 md:hidden">
          {PRIMARY_NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                classNames(
                  "shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium",
                  isActive
                    ? "bg-brand-600 text-white"
                    : "bg-slate-100 text-slate-600 dark:bg-slate-900 dark:text-slate-300"
                )
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-7xl p-4 sm:p-6">
        <Outlet />
      </main>

      <ClientVoiceAssistant />
    </div>
  );
}

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        classNames(
          "rounded-lg px-3 py-2 text-sm font-medium transition whitespace-nowrap",
          isActive
            ? "bg-brand-600 text-white"
            : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900"
        )
      }
    >
      {label}
    </NavLink>
  );
}
