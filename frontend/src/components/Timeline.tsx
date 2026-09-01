import { classNames, eventDotClass, eventLabel, fmtDateTime } from "../lib/format";

type Ev = { event_type: string; event_timestamp: string; metadata?: Record<string, any> };

export function Timeline({ events }: { events: Ev[] }) {
  if (!events || events.length === 0) {
    return <div className="py-6 text-center text-sm text-slate-400">No events recorded yet.</div>;
  }
  return (
    <ol className="relative ml-2 border-l border-slate-200 dark:border-slate-700">
      {events.map((e, i) => (
        <li key={i} className="mb-5 ml-5 last:mb-0">
          <span
            className={classNames(
              "absolute -left-[7px] mt-1 h-3.5 w-3.5 rounded-full ring-4 ring-white dark:ring-slate-900",
              eventDotClass(e.event_type)
            )}
          />
          <div className="flex flex-wrap items-center justify-between gap-x-3">
            <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              {eventLabel(e.event_type)}
            </span>
            <span className="text-xs text-slate-400">{fmtDateTime(e.event_timestamp)}</span>
          </div>
          {e.metadata && Object.keys(e.metadata).length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1.5">
              {renderMeta(e.metadata)}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

function renderMeta(meta: Record<string, any>) {
  const chips: string[] = [];
  if (meta.source) chips.push(`source: ${meta.source}`);
  if (meta.page) chips.push(meta.page);
  if (meta.user_agent_summary) chips.push(meta.user_agent_summary);
  if (meta.provider) chips.push(`via ${meta.provider}`);
  if (meta.utm && typeof meta.utm === "object" && meta.utm.utm_source)
    chips.push(`utm: ${meta.utm.utm_source}`);
  if (meta.amount) chips.push(`${meta.currency || ""} ${meta.amount}`.trim());
  if (Array.isArray(meta.recipients) && meta.recipients.length)
    chips.push(`to ${meta.recipients.join(", ")}`);
  return chips.map((c, i) => (
    <span
      key={i}
      className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400"
    >
      {c}
    </span>
  ));
}
