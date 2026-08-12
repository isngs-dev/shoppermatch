import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { classNames, initials } from "../lib/format";
import { IconCheck, IconCopy } from "./Icons";

// ------------------------------ Logo ------------------------------ //
export function Logo({ compact = false, className = "" }: { compact?: boolean; className?: string }) {
  return (
    <div className={classNames("flex items-center gap-2", className)}>
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white">
        S
      </div>
      {!compact && (
        <span className="text-[15px] font-bold tracking-tight text-slate-900 dark:text-white">
          ShopperMatch<span className="text-brand-500">.AI</span>
        </span>
      )}
    </div>
  );
}

// ------------------------------ Spinner / Loading ------------------------------ //
export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg className={classNames("animate-spin", className)} width="20" height="20" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.2" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-slate-400">
      <Spinner className="text-brand-500" />
      <span className="text-sm">{label}</span>
    </div>
  );
}

// ------------------------------ KPI card ------------------------------ //
export function KpiCard({
  label,
  value,
  sub,
  icon,
  accent = "brand",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  accent?: "brand" | "sky" | "indigo" | "violet" | "amber" | "emerald" | "rose" | "slate";
}) {
  const accents: Record<string, string> = {
    brand: "bg-brand-50 text-brand-600 dark:bg-brand-950 dark:text-brand-300",
    sky: "bg-sky-50 text-sky-600 dark:bg-sky-950 dark:text-sky-300",
    indigo: "bg-indigo-50 text-indigo-600 dark:bg-indigo-950 dark:text-indigo-300",
    violet: "bg-violet-50 text-violet-600 dark:bg-violet-950 dark:text-violet-300",
    amber: "bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-300",
    emerald: "bg-emerald-50 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-300",
    rose: "bg-rose-50 text-rose-600 dark:bg-rose-950 dark:text-rose-300",
    slate: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  };
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            {label}
          </div>
          <div className="mt-2 text-3xl font-bold text-slate-900 dark:text-white">{value}</div>
          {sub && <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{sub}</div>}
        </div>
        {icon && (
          <div className={classNames("flex h-10 w-10 items-center justify-center rounded-lg", accents[accent])}>
            {icon}
          </div>
        )}
      </div>
    </div>
  );
}

// ------------------------------ Badges ------------------------------ //
export function Badge({ className = "", children }: { className?: string; children: ReactNode }) {
  return <span className={classNames("badge", className)}>{children}</span>;
}

export function CheckCell({ on }: { on: boolean }) {
  return on ? (
    <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-300">
      <IconCheck width={13} height={13} />
    </span>
  ) : (
    <span className="text-slate-300 dark:text-slate-600">—</span>
  );
}

// ------------------------------ Avatar ------------------------------ //
export function Avatar({ name, className = "" }: { name?: string | null; className?: string }) {
  return (
    <div
      className={classNames(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-bold uppercase text-brand-700 dark:bg-brand-950 dark:text-brand-300",
        className
      )}
    >
      {initials(name)}
    </div>
  );
}

// ------------------------------ Copy button ------------------------------ //
export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn-secondary"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
        } catch {
          /* clipboard may be blocked; ignore */
        }
        setCopied(true);
        setTimeout(() => setCopied(false), 1400);
      }}
    >
      {copied ? <IconCheck width={15} height={15} /> : <IconCopy width={15} height={15} />}
      {copied ? "Copied" : label}
    </button>
  );
}

// ------------------------------ Empty state ------------------------------ //
export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-14 text-center">
      <div className="text-sm font-semibold text-slate-600 dark:text-slate-300">{title}</div>
      {hint && <div className="mt-1 max-w-sm text-xs text-slate-400">{hint}</div>}
    </div>
  );
}

// ------------------------------ Progress bar ------------------------------ //
export function ProgressBar({ value, max, className = "" }: { value: number; max: number; className?: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className={classNames("h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800", className)}>
      <div className="h-full rounded-full bg-brand-500 transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
}

// ------------------------------ Toasts ------------------------------ //
type Toast = { id: number; message: string; type: "success" | "error" | "info" };
const ToastContext = createContext<(message: string, type?: Toast["type"]) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((message: string, type: Toast["type"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, type }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3200);
  }, []);
  const colors: Record<Toast["type"], string> = {
    success: "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
    error: "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200",
    info: "border-slate-200 bg-white text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200",
  };
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[100] flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={classNames(
              "pointer-events-auto rounded-lg border px-4 py-2.5 text-sm font-medium shadow-lg",
              colors[t.type]
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
