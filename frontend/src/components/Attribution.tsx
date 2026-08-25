import { fmtDateTime } from "../lib/format";
import { IconShield, IconX } from "./Icons";

export function AttributionBadge({ attributed = true }: { attributed?: boolean }) {
  if (!attributed) {
    return (
      <span className="badge gap-1.5 bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400">
        <IconX width={13} height={13} />
        NOT YET ATTRIBUTED
      </span>
    );
  }
  return (
    <span className="badge gap-1.5 bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
      <IconShield width={13} height={13} />
      ISN ATTRIBUTED
    </span>
  );
}

type Attribution = {
  attributed?: boolean;
  channel?: string;
  source?: string;
  campaign?: string | null;
  invitation_id?: string;
  tracking_token_masked?: string;
  landing_page?: string;
  first_click?: string | null;
  visited?: string | null;
  response?: string | null;
};

export function AttributionCard({ attribution }: { attribution: Attribution }) {
  const rows: [string, string][] = [
    ["Source", attribution.source || "ISN Outreach"],
    ["Campaign", attribution.campaign || "—"],
    ["Invitation ID", attribution.invitation_id || "—"],
    ["Tracking Token", attribution.tracking_token_masked || "—"],
    ["Landing Page", attribution.landing_page || "ShopperMatch.AI"],
    ["First Click", attribution.first_click ? fmtDateTime(attribution.first_click) : "—"],
    ["Assignment Visited", attribution.visited ? fmtDateTime(attribution.visited) : "—"],
    ["Response", attribution.response ? cap(attribution.response) : "Pending"],
  ];
  return (
    <div
      className={
        "rounded-xl border p-4 " +
        (attribution.attributed
          ? "border-emerald-200 bg-emerald-50/50 dark:border-emerald-900 dark:bg-emerald-950/30"
          : "border-slate-200 bg-slate-50/50 dark:border-slate-800 dark:bg-slate-800/30")
      }
    >
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          Attribution
        </span>
        <AttributionBadge attributed={attribution.attributed} />
      </div>
      {!attribution.attributed && (
        <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
          The shopper has not yet clicked the unique ISN/ShopperMatch outreach link — attribution can
          only be claimed once the tracking link has actually been used.
        </p>
      )}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
        {rows.map(([k, v]) => (
          <div key={k} className="flex flex-col">
            <dt
              className={
                "text-[11px] font-semibold uppercase tracking-wide " +
                (attribution.attributed
                  ? "text-emerald-700/70 dark:text-emerald-300/70"
                  : "text-slate-400")
              }
            >
              {k}
            </dt>
            <dd className="text-sm font-medium text-slate-800 dark:text-slate-100">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function cap(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
