import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Funnel } from "../components/Funnel";
import {
  IconArrowRight,
  IconCampaign,
  IconCursor,
  IconMail,
  IconSend,
  IconTarget,
  IconUsers,
} from "../components/Icons";
import { Timeline } from "../components/Timeline";
import { KpiCard, Loading } from "../components/ui";
import { api } from "../lib/api";
import { eventLabel, fmtRelative } from "../lib/format";
import { useApi } from "../lib/useApi";

const FUNNEL_COLORS = ["#0ea5e9", "#6366f1", "#8b5cf6", "#f59e0b", "#10b981"];

export function Dashboard() {
  const { data, loading, error, reload } = useApi(() => api.dashboard());

  if (loading && !data) return <Loading label="Loading dashboard…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return null;

  const o = data.outreach;
  const c = data.counts;

  return (
    <div className="space-y-6">
      {/* KPI row */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <KpiCard label="Invitations Sent" value={o.sent} icon={<IconSend width={18} />} accent="sky" />
        <KpiCard label="Delivered" value={o.delivered} icon={<IconMail width={18} />} accent="indigo" />
        <KpiCard label="Opened" value={o.opened} icon={<IconMail width={18} />} accent="violet" sub={`${o.open_rate}% open rate`} />
        <KpiCard label="Clicked" value={o.clicked} icon={<IconCursor width={18} />} accent="amber" sub={`${o.click_rate}% of opens`} />
        <KpiCard label="Accepted" value={o.accepted} icon={<IconTarget width={18} />} accent="emerald" sub={`${o.acceptance_rate}% of clicks`} />
      </div>

      {/* Secondary stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard label="Active Campaigns" value={c.active_campaigns} sub={`${c.campaigns} total`} icon={<IconCampaign width={18} />} accent="brand" />
        <KpiCard label="Active Shoppers" value={c.active_shoppers} sub={`${c.shoppers} in network`} icon={<IconUsers width={18} />} accent="slate" />
        <KpiCard label="Open Shops" value={c.open_shops} sub={`${c.shops} total shops`} accent="slate" />
        <KpiCard label="Declined" value={o.declined} sub={`${o.pending} pending response`} accent="rose" />
      </div>

      {/* Charts + funnel */}
      <div className="grid gap-6 lg:grid-cols-5">
        <div className="card p-5 lg:col-span-3">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              Outreach volume by stage
            </h2>
            <Link to="/tracking" className="text-xs font-semibold text-brand-600 hover:underline">
              View tracking →
            </Link>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={o.funnel} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="stage" tick={{ fontSize: 12, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 12, fill: "#94a3b8" }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip
                  cursor={{ fill: "rgba(99,102,241,0.08)" }}
                  contentStyle={{ borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 12 }}
                />
                <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                  {o.funnel.map((_: any, i: number) => (
                    <Cell key={i} fill={FUNNEL_COLORS[i % FUNNEL_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card p-5 lg:col-span-2">
          <h2 className="mb-4 text-sm font-semibold text-slate-800 dark:text-slate-100">
            Conversion funnel
          </h2>
          <Funnel stages={o.funnel} />
        </div>
      </div>

      {/* Recent activity */}
      <div className="card p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Recent activity
          </h2>
          <button className="text-xs font-semibold text-brand-600 hover:underline" onClick={reload}>
            Refresh
          </button>
        </div>
        {data.recent_activity.length === 0 ? (
          <div className="py-6 text-center text-sm text-slate-400">No activity yet.</div>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.recent_activity.map((e: any) => (
              <li key={e.id} className="flex items-center gap-3 py-2.5">
                <span className="badge bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {eventLabel(e.event_type)}
                </span>
                <span className="text-sm text-slate-700 dark:text-slate-300">
                  {e.shopper_name || "—"}
                </span>
                <span className="hidden text-xs text-slate-400 sm:inline">{e.campaign_name}</span>
                <span className="ml-auto text-xs text-slate-400">{fmtRelative(e.event_timestamp)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card flex flex-col items-center gap-3 p-10 text-center">
      <div className="text-sm font-semibold text-rose-600">Failed to load</div>
      <div className="max-w-md text-xs text-slate-500">{message}</div>
      {onRetry && (
        <button className="btn-secondary" onClick={onRetry}>
          Retry <IconArrowRight width={15} height={15} />
        </button>
      )}
    </div>
  );
}
