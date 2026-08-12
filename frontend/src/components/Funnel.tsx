import { classNames } from "../lib/format";

type Stage = { stage: string; value: number };

const STAGE_COLORS: Record<string, string> = {
  Sent: "bg-sky-500",
  Delivered: "bg-indigo-500",
  Opened: "bg-violet-500",
  Clicked: "bg-amber-500",
  Accepted: "bg-emerald-500",
};

export function Funnel({ stages }: { stages: Stage[] }) {
  const top = stages.length ? Math.max(stages[0].value, 1) : 1;
  return (
    <div className="space-y-3">
      {stages.map((s, i) => {
        const widthPct = Math.max(4, Math.round((s.value / top) * 100));
        const prev = i > 0 ? stages[i - 1].value : s.value;
        const conv = prev > 0 ? Math.round((s.value / prev) * 100) : 0;
        return (
          <div key={s.stage}>
            <div className="mb-1 flex items-center justify-between text-sm">
              <span className="font-medium text-slate-600 dark:text-slate-300">{s.stage}</span>
              <span className="tabular-nums font-semibold text-slate-900 dark:text-white">
                {s.value.toLocaleString()}
                {i > 0 && (
                  <span className="ml-2 text-xs font-normal text-slate-400">{conv}%</span>
                )}
              </span>
            </div>
            <div className="h-7 w-full overflow-hidden rounded-lg bg-slate-100 dark:bg-slate-800">
              <div
                className={classNames("h-full rounded-lg transition-all duration-500", STAGE_COLORS[s.stage] || "bg-brand-500")}
                style={{ width: `${widthPct}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
