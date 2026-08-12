import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Badge, EmptyState, KpiCard, Loading, ProgressBar } from "../components/ui";
import { api } from "../lib/api";
import { fmtDate, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

const TABS = [
  { key: "active", label: "Active Campaigns" },
  { key: "upcoming", label: "Upcoming Campaigns" },
  { key: "completed", label: "Completed Campaigns" },
] as const;

export type PortalTab = (typeof TABS)[number]["key"];

export function CampaignsPortal({ tab }: { tab: PortalTab }) {
  const navigate = useNavigate();
  const { data, loading, error, reload } = useApi(() => api.campaigns({ status: tab }), [tab]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("newest");

  const items = useMemo(() => {
    let list = (data?.items || []) as any[];
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter(
        (c) =>
          c.name.toLowerCase().includes(q) ||
          c.client_name.toLowerCase().includes(q) ||
          (c.description || "").toLowerCase().includes(q)
      );
    }
    list = [...list];
    const pct = (c: any) => (c.total_shops ? Math.round((c.completed_shops / c.total_shops) * 100) : 0);
    switch (sort) {
      case "oldest":
        list.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
        break;
      case "deadline":
        list.sort((a, b) => new Date(a.deadline || 0).getTime() - new Date(b.deadline || 0).getTime());
        break;
      case "progress":
        list.sort((a, b) => pct(b) - pct(a));
        break;
      case "name":
        list.sort((a, b) => a.name.localeCompare(b.name));
        break;
      default:
        list.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    }
    return list;
  }, [data, query, sort]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900 dark:text-white">Campaigns</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Manage active, upcoming and completed mystery shopping campaigns.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex overflow-x-auto rounded-xl bg-slate-100 p-1 dark:bg-slate-800/70">
          {TABS.map((t) => (
            <Link
              key={t.key}
              to={`/campaigns/${t.key}`}
              className={
                "shrink-0 rounded-lg px-4 py-2 text-sm font-semibold transition " +
                (tab === t.key
                  ? "bg-brand-600 text-white shadow"
                  : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100")
              }
            >
              {t.label}
            </Link>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input
            className="input h-9 w-56"
            placeholder="Search campaigns…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select className="input h-9 w-40" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
            <option value="deadline">Deadline</option>
            <option value="progress">Progress</option>
            <option value="name">Campaign name</option>
          </select>
        </div>
      </div>

      {error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : loading && !data ? (
        <Loading label="Loading campaigns…" />
      ) : (
        <>
          <KpiRow tab={tab} items={data.items} />
          {items.length === 0 ? (
            <div className="card">
              <EmptyState
                title={`No ${tab} campaigns`}
                hint={
                  tab === "active"
                    ? "Active campaigns will appear here once a campaign is running."
                    : tab === "upcoming"
                    ? "Your scheduled campaigns will appear here."
                    : "Completed campaigns will appear here once a campaign wraps up."
                }
              />
            </div>
          ) : (
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {items.map((c: any) => (
                <CampaignCard key={c.id} c={c} tab={tab} onNavigate={navigate} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function pct(c: any) {
  return c.total_shops ? Math.round((c.completed_shops / c.total_shops) * 100) : 0;
}

function KpiRow({ tab, items }: { tab: PortalTab; items: any[] }) {
  if (tab === "active") {
    const totalShops = items.reduce((s, c) => s + (c.shops_count || 0), 0);
    const pending = items.reduce(
      (s, c) => s + Math.max(0, (c.total_shops || 0) - (c.completed_shops || 0)),
      0
    );
    const avgProgress = items.length
      ? Math.round(items.reduce((s, c) => s + pct(c), 0) / items.length)
      : 0;
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="Active Campaigns" value={items.length} accent="brand" />
        <KpiCard label="Total Shops" value={totalShops} accent="indigo" />
        <KpiCard label="Pending Shops" value={pending} accent="amber" />
        <KpiCard label="Average Progress" value={`${avgProgress}%`} accent="emerald" />
      </div>
    );
  }
  if (tab === "upcoming") {
    const totalShops = items.reduce((s, c) => s + (c.shops_count || 0), 0);
    const requiredShoppers = items.reduce((s, c) => s + (c.required_shoppers_total || 0), 0);
    const next = items
      .map((c) => c.start_date || c.deadline)
      .filter(Boolean)
      .sort((a, b) => new Date(a).getTime() - new Date(b).getTime())[0];
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="Upcoming Campaigns" value={items.length} accent="brand" />
        <KpiCard label="Total Shops" value={totalShops} accent="indigo" />
        <KpiCard label="Required Shoppers" value={requiredShoppers} accent="violet" />
        <KpiCard label="Next Start" value={next ? fmtDate(next) : "—"} accent="slate" />
      </div>
    );
  }
  const completedShops = items.reduce((s, c) => s + (c.completed_shops || 0), 0);
  const completionRate = items.length
    ? Math.round(items.reduce((s, c) => s + pct(c), 0) / items.length)
    : 0;
  const totalAccepted = items.reduce((s, c) => s + (c.outreach?.accepted || 0), 0);
  const totalDeclined = items.reduce((s, c) => s + (c.outreach?.declined || 0), 0);
  const totalDelivered = items.reduce((s, c) => s + (c.outreach?.delivered || 0), 0);
  // (accepted + declined) / delivered — how many delivered invitations got any response.
  const responseRate = totalDelivered
    ? Math.round(((totalAccepted + totalDeclined) / totalDelivered) * 100)
    : 0;
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <KpiCard label="Completed Campaigns" value={items.length} accent="brand" />
      <KpiCard label="Completed Shops" value={completedShops} accent="indigo" />
      <KpiCard label="Completion Rate" value={`${completionRate}%`} accent="emerald" />
      <KpiCard label="Response Rate" value={`${responseRate}%`} accent="violet" />
    </div>
  );
}

function CampaignCard({
  c,
  tab,
  onNavigate,
}: {
  c: any;
  tab: PortalTab;
  onNavigate: (path: string) => void;
}) {
  return (
    <div className="card flex flex-col p-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            {c.client_name}
          </div>
          <h3 className="text-base font-bold text-slate-900 dark:text-white">{c.name}</h3>
        </div>
        <Badge className={statusBadgeClass(c.status === "active" ? "accepted" : "created")}>
          {c.status}
        </Badge>
      </div>

      <p className="mt-2 line-clamp-2 text-sm text-slate-500 dark:text-slate-400">
        {c.description}
      </p>

      <div className="mt-4">
        <div className="mb-1 flex justify-between text-xs text-slate-500">
          <span>Shops completed</span>
          <span className="font-semibold">
            {c.completed_shops}/{c.total_shops}
          </span>
        </div>
        <ProgressBar value={c.completed_shops} max={c.total_shops || 1} />
      </div>

      <div className="mt-4 grid grid-cols-4 gap-2 text-center">
        <Stat label="Sent" value={c.outreach.sent} />
        <Stat label="Opened" value={c.outreach.opened} />
        <Stat label="Clicked" value={c.outreach.clicked} />
        <Stat label="Accepted" value={c.outreach.accepted} />
      </div>

      {tab === "upcoming" && c.start_date && (
        <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
          <span>Start</span>
          <span className="font-semibold text-slate-600 dark:text-slate-300">{fmtDate(c.start_date)}</span>
        </div>
      )}

      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-400 dark:border-slate-800">
        <span>{c.shops_count} shops</span>
        <span>{tab === "completed" ? "Completed" : "Deadline"} {fmtDate(c.deadline)}</span>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button className="btn-secondary" onClick={() => onNavigate(`/campaigns/${c.id}`)}>
          View Campaign
        </button>
        {tab === "active" && (
          <>
            <button className="btn-secondary" onClick={() => onNavigate(`/campaigns/${c.id}?tab=shops`)}>
              View Shops
            </button>
            <button className="btn-secondary" onClick={() => onNavigate(`/campaigns/${c.id}?tab=outreach`)}>
              Outreach
            </button>
          </>
        )}
        {tab === "upcoming" && (
          <>
            <button className="btn-secondary" onClick={() => onNavigate(`/campaigns/${c.id}?tab=shops`)}>
              View Shops
            </button>
            <button className="btn-secondary" onClick={() => onNavigate(`/campaigns/${c.id}?tab=recommendations`)}>
              AI Recommendations
            </button>
            <button className="btn-secondary" onClick={() => onNavigate(`/campaigns/${c.id}?tab=outreach`)}>
              Prepare Outreach
            </button>
          </>
        )}
        {tab === "completed" && (
          <>
            <button className="btn-secondary" onClick={() => onNavigate(`/campaigns/${c.id}?tab=shops`)}>
              View Shops
            </button>
            <button className="btn-secondary" onClick={() => onNavigate(`/campaigns/${c.id}?tab=overview`)}>
              View Report
            </button>
            <button className="btn-secondary" onClick={() => onNavigate(`/campaigns/${c.id}?tab=tracking`)}>
              View Tracking
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-slate-50 py-2 dark:bg-slate-800/50">
      <div className="text-lg font-bold text-slate-900 dark:text-white">{value}</div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
    </div>
  );
}
