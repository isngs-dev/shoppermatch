import { IconPlug } from "../components/Icons";
import { Loading } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

const STATUS_CLASS: Record<string, string> = {
  connected: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  demo: "bg-brand-100 text-brand-700 dark:bg-brand-950 dark:text-brand-300",
  fallback: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  optional: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  planned: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
};

export function Integrations() {
  const { data, loading, error, reload } = useApi(() => api.integrations());
  if (loading && !data) return <Loading label="Loading integrations…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {data.items.map((it: any) => (
        <div key={it.key} className="card p-5">
          <div className="flex items-start justify-between">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 text-slate-500 dark:bg-slate-800">
              <IconPlug />
            </div>
            <span className={"badge capitalize " + (STATUS_CLASS[it.status] || STATUS_CLASS.optional)}>
              {it.status}
            </span>
          </div>
          <h3 className="mt-3 text-base font-semibold text-slate-900 dark:text-white">{it.name}</h3>
          <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
            {it.category}
          </div>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{it.detail}</p>
        </div>
      ))}
    </div>
  );
}
