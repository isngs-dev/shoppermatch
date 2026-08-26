import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { classNames } from "../lib/format";
import { useTheme } from "../lib/theme";
import { IconLogout, IconMoon, IconSun } from "./Icons";
import { Avatar, Logo } from "./ui";

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
  { to: "/client/outreach?tab=batch", label: "Email Automation" },
];

const MORE_NAV = [
  { to: "/client/insights", label: "Insights" },
  { to: "/client/reports", label: "Reports" },
  { to: "/client/profile", label: "Profile" },
];

const ALL_NAV = [...PRIMARY_NAV, ...MORE_NAV];

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
            <NavDropdown label="More" items={MORE_NAV} />
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <button className="btn-ghost" onClick={toggle} aria-label="Toggle theme">
              {theme === "dark" ? <IconSun /> : <IconMoon />}
            </button>
            <div className="hidden items-center gap-2 sm:flex">
              <Avatar name={user?.name} className="h-8 w-8" />
              <div className="leading-tight">
                <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">{user?.name}</div>
                <div className="text-[11px] text-slate-400">{user?.client_name}</div>
              </div>
            </div>
            <button className="btn-ghost" onClick={logout} aria-label="Log out" title="Log out">
              <IconLogout />
            </button>
          </div>
        </div>
        {/* Mobile nav row */}
        <nav className="flex gap-1 overflow-x-auto border-t border-slate-100 px-4 py-2 dark:border-slate-900 md:hidden">
          {ALL_NAV.map((n) => (
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

function NavDropdown({ label, items }: { label: string; items: { to: string; label: string }[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const active = items.some((i) => location.pathname.startsWith(i.to));

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  useEffect(() => setOpen(false), [location.pathname]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={classNames(
          "flex items-center gap-1 rounded-lg px-3 py-2 text-sm font-medium transition whitespace-nowrap",
          active || open
            ? "bg-brand-600 text-white"
            : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900"
        )}
      >
        {label}
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className={classNames("transition", open && "rotate-180")}>
          <path d="M2.5 4.5L6 8l3.5-3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 w-48 rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg dark:border-slate-700 dark:bg-slate-900">
          {items.map((i) => (
            <NavLink
              key={i.to}
              to={i.to}
              className={({ isActive }) =>
                classNames(
                  "block rounded-lg px-3 py-2 text-sm font-medium transition",
                  isActive
                    ? "bg-brand-600 text-white"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900"
                )
              }
            >
              {i.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}
