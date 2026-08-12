import { useEffect, useState } from "react";
import { IconSparkles } from "../components/Icons";
import { Avatar, Badge, Loading } from "../components/ui";
import { api } from "../lib/api";
import { classNames } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

const CONF_CLASS: Record<string, string> = {
  High: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  Medium: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  Low: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
};

export function Recommendations() {
  const shops = useApi(() => api.shops());
  const [shopId, setShopId] = useState("");

  useEffect(() => {
    if (shops.data && !shopId) setShopId(shops.data.items[0]?.id || "");
  }, [shops.data]);

  const recs = useApi(() => api.recommendations(shopId || undefined), [shopId]);

  return (
    <div className="space-y-5">
      <div className="card flex flex-wrap items-center gap-3 p-4">
        <div className="flex items-center gap-2 text-brand-600">
          <IconSparkles />
          <span className="text-sm font-semibold">Match shoppers to shop</span>
        </div>
        <select
          className="input h-9 w-80"
          value={shopId}
          onChange={(e) => setShopId(e.target.value)}
        >
          {shops.data?.items.map((s: any) => (
            <option key={s.id} value={s.id}>
              {s.shop_name} — {s.city} ({s.category})
            </option>
          ))}
        </select>
        <span className="text-xs text-slate-400">
          Rule-based scoring — explainable, not a black-box ML model.
        </span>
      </div>

      {recs.error ? (
        <ErrorBox message={recs.error} onRetry={recs.reload} />
      ) : recs.loading && !recs.data ? (
        <Loading label="Scoring shoppers…" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {recs.data.recommendations.map((r: any, i: number) => (
            <div key={r.shopper_id} className="card p-5">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="relative">
                    <Avatar name={r.shopper_name} className="h-11 w-11" />
                    <span className="absolute -left-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-slate-900 text-[10px] font-bold text-white">
                      {i + 1}
                    </span>
                  </div>
                  <div>
                    <div className="font-semibold text-slate-900 dark:text-white">{r.shopper_name}</div>
                    <div className="text-xs text-slate-400">
                      {r.city} · {r.previous_assignments} jobs ·{" "}
                      {r.distance_km != null ? `${r.distance_km} km` : "distance n/a"}
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-extrabold text-brand-600 dark:text-brand-400">
                    {r.match_score}%
                  </div>
                  <Badge className={CONF_CLASS[r.confidence]}>{r.confidence}</Badge>
                </div>
              </div>

              <div className="mt-4 space-y-2">
                {r.breakdown.map((b: any) => (
                  <div key={b.label}>
                    <div className="mb-0.5 flex items-center justify-between text-xs">
                      <span className="text-slate-500 dark:text-slate-400">{b.label}</span>
                      <span className="font-semibold text-slate-700 dark:text-slate-200">
                        +{b.points}
                        <span className="font-normal text-slate-400"> / {b.max}</span>
                      </span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                      <div
                        className={classNames("h-full rounded-full bg-brand-500")}
                        style={{ width: `${Math.round((b.points / b.max) * 100)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
