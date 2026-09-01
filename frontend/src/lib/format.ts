// Formatting + small presentation helpers.

export function fmtDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

export function fmtRelative(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso).getTime();
  if (isNaN(d)) return "—";
  const diff = Date.now() - d;
  const s = Math.round(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.round(h / 24);
  return `${days}d ago`;
}

const CURRENCY_SYMBOL: Record<string, string> = {
  INR: "₹",
  USD: "$",
  EUR: "€",
  GBP: "£",
};

export function fmtMoney(amount?: number | null, currency = "INR"): string {
  if (amount === null || amount === undefined) return "—";
  const symbol = CURRENCY_SYMBOL[currency] || "";
  return `${symbol}${amount.toLocaleString()}`;
}

export function fmtPct(n?: number | null): string {
  if (n === null || n === undefined) return "—";
  return `${n}%`;
}

// Human-friendly label for an event type.
export const EVENT_LABELS: Record<string, string> = {
  invitation_created: "Invitation Created",
  email_sent: "Email Sent",
  email_delivered: "Email Delivered",
  email_opened: "Email Opened",
  link_clicked: "Invitation Link Clicked",
  assignment_visited: "Assignment Page Visited",
  assignment_accepted: "Assignment Accepted",
  assignment_declined: "Assignment Declined",
  email_bounced: "Email Bounced",
  email_failed: "Email Failed",
  email_deferred: "Email Deferred",
  assignment_completed: "Shop Completed",
  bonus_reminder_sent: "Bonus Reminder Sent to Client",
};

export function eventLabel(type: string): string {
  return EVENT_LABELS[type] || type;
}

// Tailwind classes for status badges.
export function statusBadgeClass(status: string): string {
  const map: Record<string, string> = {
    created: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    sent: "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
    delivered: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300",
    opened: "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300",
    clicked: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
    visited: "bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300",
    accepted: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    declined: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
    completed: "bg-teal-100 text-teal-700 dark:bg-teal-950 dark:text-teal-300",
    pending: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  };
  return map[status] || map.created;
}

export function eventDotClass(type: string): string {
  const map: Record<string, string> = {
    invitation_created: "bg-slate-400",
    email_sent: "bg-sky-500",
    email_delivered: "bg-indigo-500",
    email_opened: "bg-violet-500",
    link_clicked: "bg-amber-500",
    assignment_visited: "bg-orange-500",
    assignment_accepted: "bg-emerald-500",
    assignment_declined: "bg-rose-500",
    email_bounced: "bg-rose-500",
    email_failed: "bg-rose-500",
    email_deferred: "bg-amber-500",
    assignment_completed: "bg-teal-500",
    bonus_reminder_sent: "bg-amber-600",
  };
  return map[type] || "bg-slate-400";
}

// Human-friendly elapsed duration between two ISO timestamps, e.g. "4m 30s".
export function fmtDuration(fromIso?: string | null, toIso?: string | null): string | null {
  if (!fromIso || !toIso) return null;
  const ms = new Date(toIso).getTime() - new Date(fromIso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  const hours = Math.floor(minutes / 60);
  if (hours === 0) return `${minutes}m ${seconds}s`;
  return `${hours}h ${minutes % 60}m`;
}

export function initials(name?: string | null): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return (parts[0]?.[0] || "") + (parts[1]?.[0] || "");
}

export function classNames(...xs: (string | false | null | undefined)[]): string {
  return xs.filter(Boolean).join(" ");
}
