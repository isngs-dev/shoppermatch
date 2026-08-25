import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { IconArrowRight, IconCampaign, IconTarget, IconUsers } from "../../components/Icons";
import { Badge, KpiCard, Loading, ProgressBar } from "../../components/ui";
import { api } from "../../lib/api";
import { classNames, fmtDate } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { ErrorBox } from "../Dashboard";

const FUNNEL_COLORS = ["#0ea5e9", "#6366f1", "#8b5cf6", "#f59e0b", "#10b981", "#f43f5e"];
const HEALTH_COLORS = { on_track: "#10b981", attention: "#f59e0b", completed: "#94a3b8" };

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

const BUCKET_BADGE: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  upcoming: "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300",
};

export function ClientDashboard() {
  const { data, loading, error, reload } = useApi(() => api.clientDashboard());
  if (loading && !data) return <Loading label="Loading your dashboard…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return null;

  const health = data.campaign_health;
  const healthTotal = health.on_track + health.attention + health.completed;
  const outreach = data.outreach || { sent: 0, opened: 0, clicked: 0, accepted: 0, declined: 0 };
  const campaigns = data.campaigns || [];

  const healthData = [
    { key: "on_track", name: "On Track", value: health.on_track },
    { key: "attention", name: "Attention Required", value: health.attention },
    { key: "completed", name: "Completed", value: health.completed },
  ].filter((d) => d.value > 0);

  const funnelData = [
    { stage: "Sent", value: outreach.sent },
    { stage: "Opened", value: outreach.opened },
    { stage: "Clicked", value: outreach.clicked },
    { stage: "Accepted", value: outreach.accepted },
    { stage: "Declined", value: outreach.declined },
  ];

  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="card overflow-hidden bg-gradient-to-br from-brand-600 via-indigo-600 to-violet-700 p-6 text-white">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-white/80">{greeting()}</p>
            <h1 className="mt-1 text-2xl font-bold">{data.client_name}</h1>
            <p className="mt-1 text-sm text-white/80">
              Here's how your mystery-shopping campaigns are progressing.
            </p>
          </div>
          <div className="text-right">
            <div className="text-4xl font-extrabold leading-none">{data.overall_progress}%</div>
            <div className="mt-1 text-xs font-medium uppercase tracking-wide text-white/70">
              Overall Progress
            </div>
          </div>
        </div>
        <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-white/20">
          <div
            className="h-full rounded-full bg-white transition-all"
            style={{ width: `${Math.min(100, data.overall_progress)}%` }}
          />
        </div>
      </div>

      {/* KPI row — clickable */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Link to="/client/campaigns/active" className="transition hover:-translate-y-0.5">
          <KpiCard label="Active Campaigns" value={data.active_campaigns} icon={<IconCampaign width={18} />} accent="brand" />
        </Link>
        <Link to="/client/campaigns/upcoming" className="transition hover:-translate-y-0.5">
          <KpiCard label="Upcoming Campaigns" value={data.upcoming_campaigns} icon={<IconCampaign width={18} />} accent="sky" />
        </Link>
        <Link to="/client/campaigns/completed" className="transition hover:-translate-y-0.5">
          <KpiCard label="Completed Campaigns" value={data.completed_campaigns} icon={<IconTarget width={18} />} accent="emerald" />
        </Link>
        <Link to="/client/campaigns" className="transition hover:-translate-y-0.5">
          <KpiCard
            label="Shops"
            value={`${data.completed_shops}/${data.total_shops}`}
            sub={`${data.pending_shops} pending`}
            icon={<IconUsers width={18} />}
            accent="slate"
          />
        </Link>
      </div>

      {/* Outreach funnel + Campaign health */}
      <div className="grid gap-6 lg:grid-cols-5">
        <div className="card p-5 lg:col-span-3">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              Outreach funnel (all campaigns)
            </h2>
            <Link to="/client/outreach" className="flex items-center gap-1 text-xs font-semibold text-brand-600 hover:underline dark:text-brand-400">
              Go to Outreach <IconArrowRight width={12} />
            </Link>
          </div>
          {outreach.sent === 0 ? (
            <div className="flex h-56 items-center justify-center text-sm text-slate-400">
              No outreach sent yet.
            </div>
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={funnelData} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="stage" tick={{ fontSize: 12, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 12, fill: "#94a3b8" }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip
                    cursor={{ fill: "rgba(99,102,241,0.08)" }}
                    contentStyle={{ borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 12 }}
                  />
                  <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                    {funnelData.map((_, i) => (
                      <Cell key={i} fill={FUNNEL_COLORS[i % FUNNEL_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="mt-4 grid grid-cols-3 gap-3 text-center sm:grid-cols-5">
            {funnelData.map((f, i) => (
              <div key={f.stage}>
                <div className="text-lg font-bold" style={{ color: FUNNEL_COLORS[i % FUNNEL_COLORS.length] }}>
                  {f.value}
                </div>
                <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{f.stage}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="card p-5 lg:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-800 dark:text-slate-100">Campaign Health</h2>
          {healthTotal === 0 ? (
            <div className="flex h-48 items-center justify-center text-sm text-slate-400">No campaigns yet.</div>
          ) : (
            <>
              <div className="relative h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={healthData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={50}
                      outerRadius={75}
                      paddingAngle={healthData.length > 1 ? 3 : 0}
                      strokeWidth={0}
                    >
                      {healthData.map((d) => (
                        <Cell key={d.key} fill={HEALTH_COLORS[d.key as keyof typeof HEALTH_COLORS]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 12 }} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <div className="text-2xl font-bold text-slate-900 dark:text-white">{healthTotal}</div>
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Campaigns</div>
                </div>
              </div>
              <div className="mt-3 space-y-1.5">
                <HealthRow label="On Track" value={health.on_track} color={HEALTH_COLORS.on_track} />
                <HealthRow label="Attention Required" value={health.attention} color={HEALTH_COLORS.attention} />
                <HealthRow label="Completed" value={health.completed} color={HEALTH_COLORS.completed} />
              </div>
            </>
          )}
        </div>
      </div>

      {/* Your campaigns */}
      <div className="card p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Your Campaigns</h2>
          <Link to="/client/campaigns" className="flex items-center gap-1 text-xs font-semibold text-brand-600 hover:underline dark:text-brand-400">
            View all <IconArrowRight width={12} />
          </Link>
        </div>
        {campaigns.length === 0 ? (
          <div className="flex h-24 items-center justify-center text-sm text-slate-400">
            No active or upcoming campaigns.
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {campaigns.map((c: any) => (
              <Link
                key={c.id}
                to={`/client/campaigns/${c.id}`}
                className="group rounded-xl border border-slate-100 p-4 transition hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-md dark:border-slate-800 dark:hover:border-brand-700"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 font-semibold text-slate-900 group-hover:text-brand-600 dark:text-white dark:group-hover:text-brand-400">
                    <span className="line-clamp-2">{c.name}</span>
                  </div>
                  <Badge className={classNames("shrink-0", BUCKET_BADGE[c.bucket] || BUCKET_BADGE.active)}>
                    {c.bucket}
                  </Badge>
                </div>
                <div className="mt-3">
                  <div className="mb-1 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                    <span>{c.completed_shops}/{c.total_shops} shops</span>
                    <span className="font-semibold text-slate-700 dark:text-slate-200">{c.progress}%</span>
                  </div>
                  <ProgressBar value={c.progress} max={100} />
                </div>
                {c.deadline && (
                  <div className="mt-2 text-[11px] text-slate-400">Deadline {fmtDate(c.deadline)}</div>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>

      <div className="text-center">
        <Link to="/client/campaigns" className="btn-primary inline-flex px-6 py-2.5">
          View My Campaigns
        </Link>
      </div>
    </div>
  );
}

function HealthRow({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
        {label}
      </span>
      <span className="font-semibold text-slate-800 dark:text-slate-100">{value}</span>
    </div>
  );
}
