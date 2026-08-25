import { useState } from "react";
import { IconLightbulb, IconSend, IconShield } from "../components/Icons";
import { Loading, Spinner, useToast } from "../components/ui";
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
    <div className="space-y-6">
      <AskAiCard />

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

      <div className="grid gap-6 lg:grid-cols-2">
        <DataQualityCard />
        <AnomaliesCard />
      </div>
    </div>
  );
}

function AskAiCard() {
  const toast = useToast();
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<any | null>(null);

  async function ask() {
    if (!question.trim()) return;
    setAsking(true);
    setAnswer(null);
    try {
      const res = await api.aiAsk(question.trim());
      setAnswer(res);
    } catch (e: any) {
      toast(e?.message || "Failed to get an answer", "error");
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="card p-5">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-700 dark:text-slate-200">
        ✨ Ask AI about your data
        <span className="text-xs font-normal text-slate-400">real-time queries over the existing database</span>
      </div>
      <div className="mt-3 flex gap-2">
        <input
          className="input flex-1"
          placeholder="e.g. Which campaign has the lowest acceptance rate?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
        />
        <button className="btn-primary px-4" onClick={ask} disabled={asking || !question.trim()}>
          {asking ? <Spinner /> : <IconSend width={16} height={16} />}
        </button>
      </div>
      {answer && (
        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-800/50 dark:text-slate-300">
          {answer.answer}
        </div>
      )}
    </div>
  );
}

function DataQualityCard() {
  const { data, loading, error } = useApi(() => api.aiDataQuality());
  return (
    <div className="card p-5">
      <h3 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-100">Data quality</h3>
      {loading && !data ? (
        <Spinner />
      ) : error ? (
        <p className="text-sm text-rose-500">{error}</p>
      ) : !data.alerts?.some((a: any) => a.count > 0) ? (
        <p className="text-sm text-emerald-600 dark:text-emerald-400">No data quality issues detected.</p>
      ) : (
        <div className="space-y-2">
          {data.alerts
            .filter((a: any) => a.count > 0)
            .map((alert: any, i: number) => (
              <div key={i} className="flex items-start justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm dark:border-amber-900 dark:bg-amber-950/40">
                <span className="text-slate-700 dark:text-slate-300">{alert.message}</span>
                <span className="shrink-0 font-semibold text-amber-600 dark:text-amber-400">{alert.count}</span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

function AnomaliesCard() {
  const { data, loading, error } = useApi(() => api.aiAnomalies());
  return (
    <div className="card p-5">
      <div className="mb-3 flex items-center gap-2">
        <IconShield className="text-slate-400" width={16} height={16} />
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Anomaly flags</h3>
      </div>
      {loading && !data ? (
        <Spinner />
      ) : error ? (
        <p className="text-sm text-rose-500">{error}</p>
      ) : !data.items?.length ? (
        <p className="text-sm text-emerald-600 dark:text-emerald-400">No anomalies flagged — nothing needs review.</p>
      ) : (
        <div className="space-y-3">
          {data.items.map((a: any) => (
            <div key={a.shopper_id} className="rounded-lg border border-rose-200 bg-rose-50 p-3 dark:border-rose-900 dark:bg-rose-950/40">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-slate-900 dark:text-white">{a.shopper_name}</span>
                <span className="text-xs font-semibold text-rose-600 dark:text-rose-400">Risk {a.risk_score}</span>
              </div>
              <ul className="mt-1 list-disc pl-4 text-xs text-slate-600 dark:text-slate-400">
                {a.signals.map((s: string, i: number) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
              <p className="mt-1 text-xs italic text-slate-400">{a.status}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
