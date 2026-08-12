import { IconLightbulb } from "../components/Icons";
import { Loading } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

const SEVERITY: Record<string, { dot: string; ring: string }> = {
  warning: { dot: "bg-amber-500", ring: "border-amber-200 dark:border-amber-900" },
  success: { dot: "bg-emerald-500", ring: "border-emerald-200 dark:border-emerald-900" },
  info: { dot: "bg-brand-500", ring: "border-slate-200 dark:border-slate-800" },
};

export function Insights() {
  const { data, loading, error, reload } = useApi(() => api.insights());
  if (loading && !data) return <Loading label="Generating insights…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  const coverage: [string, number][] = Object.entries(data.city_coverage || {});
  const maxCov = Math.max(1, ...coverage.map(([, n]) => n));

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-700 dark:text-slate-200">
          <IconLightbulb className="text-amber-500" /> AI insights
          <span className="text-xs font-normal text-slate-400">informational recommendations</span>
        </div>
        {data.insights.map((ins: any, i: number) => {
          const sev = SEVERITY[ins.severity] || SEVERITY.info;
          return (
            <div key={i} className={"card border p-5 " + sev.ring}>
              <div className="flex items-center gap-2">
                <span className={"h-2.5 w-2.5 rounded-full " + sev.dot} />
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white">{ins.title}</h3>
              </div>
              <p className="mt-1.5 pl-5 text-sm text-slate-600 dark:text-slate-400">{ins.message}</p>
            </div>
          );
        })}
        <p className="text-xs text-slate-400">
          Insights are rule/threshold based — the platform does not claim a trained predictive model.
        </p>
      </div>

      <div className="card h-fit p-5">
        <h3 className="mb-4 text-sm font-semibold text-slate-800 dark:text-slate-100">
          Shopper coverage by city
        </h3>
        <div className="space-y-3">
          {coverage.map(([city, n]) => (
            <div key={city}>
              <div className="mb-1 flex justify-between text-sm">
                <span className="text-slate-600 dark:text-slate-300">{city}</span>
                <span className="font-semibold text-slate-900 dark:text-white">{n}</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                <div
                  className={"h-full rounded-full " + (n < 2 ? "bg-amber-500" : "bg-brand-500")}
                  style={{ width: `${Math.round((n / maxCov) * 100)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
