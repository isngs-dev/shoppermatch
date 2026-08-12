import { fmtDateTime } from "../lib/format";
import { IconShield } from "./Icons";

export function AttributionBadge() {
  return (
    <span className="badge gap-1.5 bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
      <IconShield width={13} height={13} />
      ISN ATTRIBUTED
    </span>
  );
}

type Attribution = {
  source?: string;
  campaign?: string | null;
  invitation_id?: string;
  tracking_token_masked?: string;
  landing_page?: string;
  first_click?: string | null;
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
    ["Response", attribution.response ? cap(attribution.response) : "Pending"],
  ];
  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 dark:border-emerald-900 dark:bg-emerald-950/30">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-semibold text-emerald-800 dark:text-emerald-200">
          Attribution
        </span>
        <AttributionBadge />
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
        {rows.map(([k, v]) => (
          <div key={k} className="flex flex-col">
            <dt className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700/70 dark:text-emerald-300/70">
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
