import { useEffect, useState } from "react";
import { Funnel } from "../components/Funnel";
import { InvitationDrawer } from "../components/InvitationDrawer";
import {
  IconCursor,
  IconMail,
  IconSend,
  IconTarget,
} from "../components/Icons";
import { Badge, CheckCell, KpiCard, Loading } from "../components/ui";
import { api } from "../lib/api";
import { classNames, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

export function Tracking() {
  const summary = useApi(() => api.trackingSummary());
  const list = useApi(() => api.invitations({ limit: 500 }));
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  function refresh() {
    summary.reload();
    list.reload();
  }

  useEffect(() => {
    const interval = window.setInterval(refresh, 4000);
    return () => window.clearInterval(interval);
  }, [summary.reload, list.reload]);

  if ((summary.loading && !summary.data) || (list.loading && !list.data))
    return <Loading label="Loading tracking data…" />;
  if (summary.error) return <ErrorBox message={summary.error} onRetry={refresh} />;

  const s = summary.data;
  const rows = (list.data?.items || []).filter((r: any) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      (r.shopper_name || "").toLowerCase().includes(q) ||
      (r.shopper_email || "").toLowerCase().includes(q) ||
      (r.campaign_name || "").toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-6">
      {/* KPIs */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <KpiCard label="Sent" value={s.sent} icon={<IconSend width={18} />} accent="sky" />
        <KpiCard label="Delivered" value={s.delivered} icon={<IconMail width={18} />} accent="indigo" />
        <KpiCard label="Opened" value={s.opened} icon={<IconMail width={18} />} accent="violet" />
        <KpiCard label="Clicked" value={s.clicked} icon={<IconCursor width={18} />} accent="amber" />
        <KpiCard label="Accepted" value={s.accepted} icon={<IconTarget width={18} />} accent="emerald" />
        <KpiCard label="Declined" value={s.declined} accent="rose" />
      </div>

      {/* Rates + funnel */}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="card p-5">
          <h2 className="mb-4 text-sm font-semibold text-slate-800 dark:text-slate-100">Rates</h2>
          <div className="space-y-4">
            <RateRow label="Delivery rate" value={s.delivery_rate} hint="delivered ÷ sent" color="bg-indigo-500" />
            <RateRow label="Open rate" value={s.open_rate} hint="opened ÷ delivered" color="bg-violet-500" />
            <RateRow label="Click rate" value={s.click_rate} hint="clicked ÷ opened" color="bg-amber-500" />
            <RateRow label="Acceptance rate" value={s.acceptance_rate} hint="accepted ÷ clicked" color="bg-emerald-500" />
          </div>
        </div>
        <div className="card p-5 lg:col-span-2">
          <h2 className="mb-4 text-sm font-semibold text-slate-800 dark:text-slate-100">
            Outreach funnel
          </h2>
          <Funnel stages={s.funnel} />
        </div>
      </div>

      {/* Table */}
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4 dark:border-slate-800">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Tracked invitations
            <span className="ml-2 text-xs font-normal text-slate-400">{rows.length}</span>
            <span className="ml-2 text-[11px] font-normal text-emerald-600 dark:text-emerald-400">Live: refreshes every 4s</span>
          </h2>
          <div className="flex items-center gap-2">
            <input
              className="input h-9 w-52"
              placeholder="Search shopper / campaign…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button className="btn-secondary h-9" onClick={refresh}>
              Refresh
            </button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead className="border-b border-slate-100 dark:border-slate-800">
              <tr>
                <th className="th">Shopper</th>
                <th className="th">Campaign</th>
                <th className="th hidden md:table-cell">Email</th>
                <th className="th text-center">Sent</th>
                <th className="th text-center">Deliv.</th>
                <th className="th text-center">Opened</th>
                <th className="th text-center">Clicked</th>
                <th className="th">Response</th>
                <th className="th hidden lg:table-cell">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
              {rows.map((r: any) => (
                <tr
                  key={r.id}
                  className="cursor-pointer transition hover:bg-slate-50 dark:hover:bg-slate-800/40"
                  onClick={() => setSelected(r.id)}
                >
                  <td className="td font-medium text-slate-800 dark:text-slate-100">
                    {r.shopper_name}
                    <div className="text-[11px] font-normal text-slate-400">{r.reference}</div>
                  </td>
                  <td className="td">{r.campaign_name}</td>
                  <td className="td hidden text-slate-500 md:table-cell">{r.shopper_email}</td>
                  <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.sent_at} /></div></td>
                  <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.delivered_at} /></div></td>
                  <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.opened_at} /></div></td>
                  <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.clicked_at} /></div></td>
                  <td className="td">
                    <Badge className={statusBadgeClass(r.response || "pending")}>
                      {r.response ? cap(r.response) : "Pending"}
                    </Badge>
                  </td>
                  <td className="td hidden lg:table-cell">
                    <span className="badge bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300">
                      ISN Email
                    </span>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="td py-10 text-center text-slate-400">
                    No invitations match your search.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selected && <InvitationDrawer invitationId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function RateRow({ label, value, hint, color }: { label: string; value: number; hint: string; color: string }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-sm font-medium text-slate-600 dark:text-slate-300">{label}</span>
        <span className="text-sm font-bold text-slate-900 dark:text-white">{value}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div className={classNames("h-full rounded-full", color)} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
      <div className="mt-1 text-[11px] text-slate-400">{hint}</div>
    </div>
  );
}

function cap(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
