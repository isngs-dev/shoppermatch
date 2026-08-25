import { useEffect, useRef, useState } from "react";
import { IconBell } from "./Icons";
import { api } from "../lib/api";
import { classNames, fmtRelative } from "../lib/format";
import { useApi } from "../lib/useApi";

const LAST_SEEN_KEY = "sm_notifications_last_seen";

const SEVERITY_DOT: Record<string, string> = {
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  info: "bg-brand-500",
};

export function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const [lastSeen, setLastSeen] = useState<string>(() => localStorage.getItem(LAST_SEEN_KEY) || "");
  const ref = useRef<HTMLDivElement>(null);
  const { data, reload } = useApi(() => api.notifications(30));

  // Notifications are derived live from real invitation/campaign data, not a
  // stored feed — poll for freshness the same way Tracking does.
  useEffect(() => {
    const id = window.setInterval(reload, 20000);
    return () => window.clearInterval(id);
  }, [reload]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const items: any[] = data?.items || [];
  const unreadCount = lastSeen ? items.filter((n) => n.timestamp > lastSeen).length : items.length;

  function toggle() {
    setOpen((v) => {
      const next = !v;
      if (next) {
        // Opening the panel marks everything currently loaded as read.
        const now = new Date().toISOString();
        localStorage.setItem(LAST_SEEN_KEY, now);
        setLastSeen(now);
      }
      return next;
    });
  }

  return (
    <div className="relative" ref={ref}>
      <button className="btn-ghost relative" onClick={toggle} aria-label="Notifications">
        <IconBell width={18} height={18} />
        {unreadCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-30 w-80 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900 sm:w-96">
          <div className="border-b border-slate-100 px-4 py-3 dark:border-slate-800">
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Notifications</h3>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {items.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-slate-400">No notifications yet.</div>
            ) : (
              items.map((n) => (
                <div
                  key={n.id}
                  className="flex gap-2.5 border-b border-slate-50 px-4 py-3 last:border-0 dark:border-slate-800/60"
                >
                  <span className={classNames("mt-1.5 h-2 w-2 shrink-0 rounded-full", SEVERITY_DOT[n.severity] || SEVERITY_DOT.info)} />
                  <div className="min-w-0">
                    <div className="text-xs font-semibold text-slate-800 dark:text-slate-100">{n.title}</div>
                    <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{n.message}</div>
                    <div className="mt-1 text-[10px] text-slate-400">{fmtRelative(n.timestamp)}</div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
