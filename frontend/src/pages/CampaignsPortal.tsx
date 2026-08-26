import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip } from "recharts";
import {
  IconCampaign,
  IconClock,
  IconTarget,
  IconUsers,
} from "../components/Icons";
import { Badge, EmptyState, KpiCard, Loading, ProgressBar, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
import { classNames, fmtDate, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

const MINI_FUNNEL_COLORS = ["#0ea5e9", "#8b5cf6", "#f59e0b", "#10b981"];

const HERO_COPY: Record<PortalTab, { title: string; sub: string; gradient: string }> = {
  active: {
    title: "Active Campaigns",
    sub: "Campaigns currently running — outreach and shop visits in progress.",
    gradient: "from-emerald-600 via-teal-600 to-brand-600",
  },
  upcoming: {
    title: "Upcoming Campaigns",
    sub: "Scheduled campaigns being prepared ahead of their start date.",
    gradient: "from-violet-600 via-indigo-600 to-brand-600",
  },
  completed: {
    title: "Completed Campaigns",
    sub: "Wrapped-up campaigns — final performance and reporting.",
    gradient: "from-slate-700 via-slate-600 to-brand-700",
  },
};

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
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkAction, setBulkAction] = useState<"automation" | "status" | null>(null);

  // Switching tabs clears any cross-tab-stale selection.
  useEffect(() => {
    setSelected(new Set());
  }, [tab]);

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function clearSelection() {
    setSelected(new Set());
  }

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

  const hero = HERO_COPY[tab];

  return (
    <div className="space-y-6">
      <div className={classNames("card overflow-hidden bg-gradient-to-br p-6 text-white", hero.gradient)}>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold">{hero.title}</h1>
            <p className="mt-1 text-sm text-white/80">{hero.sub}</p>
          </div>
          {!loading && data && (
            <div className="text-right">
              <div className="text-4xl font-extrabold leading-none">{data.items.length}</div>
              <div className="mt-1 text-xs font-medium uppercase tracking-wide text-white/70">
                {tab === "active" ? "Running now" : tab === "upcoming" ? "Scheduled" : "Wrapped up"}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex overflow-x-auto rounded-xl bg-slate-100 p-1 dark:bg-slate-800/70">
          {TABS.map((t) => (
            <Link
              key={t.key}
              to={`/client/campaigns/${t.key}`}
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
            <>
              <div className="flex items-center justify-between text-xs text-slate-400">
                <button
                  className="font-semibold text-brand-600 hover:underline dark:text-brand-400"
                  onClick={() =>
                    setSelected((prev) =>
                      prev.size === items.length ? new Set() : new Set(items.map((c: any) => c.id))
                    )
                  }
                >
                  {selected.size === items.length ? "Deselect all" : `Select all (${items.length})`}
                </button>
                {selected.size > 0 && <span>{selected.size} selected</span>}
              </div>
              <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
                {items.map((c: any) => (
                  <CampaignCard
                    key={c.id}
                    c={c}
                    tab={tab}
                    onNavigate={navigate}
                    selected={selected.has(c.id)}
                    onToggleSelect={() => toggleSelect(c.id)}
                  />
                ))}
              </div>
            </>
          )}
        </>
      )}

      {selected.size > 0 && (
        <BulkActionBar
          selectedIds={Array.from(selected)}
          selectedCampaigns={items.filter((c: any) => selected.has(c.id))}
          tab={tab}
          onClear={clearSelection}
          onOpenAutomation={() => setBulkAction("automation")}
          onOpenStatus={() => setBulkAction("status")}
        />
      )}

      {bulkAction === "automation" && (
        <BulkAutomationModal
          campaignIds={Array.from(selected)}
          campaigns={items.filter((c: any) => selected.has(c.id))}
          onClose={() => setBulkAction(null)}
          onDone={() => {
            setBulkAction(null);
            clearSelection();
            reload();
          }}
        />
      )}

      {bulkAction === "status" && (
        <BulkStatusModal
          campaignIds={Array.from(selected)}
          campaigns={items.filter((c: any) => selected.has(c.id))}
          onClose={() => setBulkAction(null)}
          onDone={() => {
            setBulkAction(null);
            clearSelection();
            reload();
          }}
        />
      )}
    </div>
  );
}

function exportCampaignsCsv(campaigns: any[]) {
  const headers = [
    "Name", "Client", "Status", "Shops", "Completed Shops", "Progress %",
    "Sent", "Opened", "Clicked", "Accepted", "Declined", "Deadline",
  ];
  const rows = campaigns.map((c) => [
    c.name, c.client_name, c.status, c.total_shops, c.completed_shops,
    c.total_shops ? Math.round((c.completed_shops / c.total_shops) * 100) : 0,
    c.outreach?.sent ?? 0, c.outreach?.opened ?? 0, c.outreach?.clicked ?? 0,
    c.outreach?.accepted ?? 0, c.outreach?.declined ?? 0, c.deadline ? fmtDate(c.deadline) : "",
  ]);
  const csv = [headers, ...rows]
    .map((r) => r.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(","))
    .join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `campaigns-report-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function BulkActionBar({
  selectedIds,
  selectedCampaigns,
  tab,
  onClear,
  onOpenAutomation,
  onOpenStatus,
}: {
  selectedIds: string[];
  selectedCampaigns: any[];
  tab: PortalTab;
  onClear: () => void;
  onOpenAutomation: () => void;
  onOpenStatus: () => void;
}) {
  return (
    <div className="sticky bottom-4 z-10 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
        {selectedIds.length} campaign{selectedIds.length > 1 ? "s" : ""} selected
      </div>
      <div className="ml-auto flex flex-wrap gap-2">
        {tab !== "completed" && (
          <button className="btn-primary h-9" onClick={onOpenAutomation}>
            ✨ Bulk-Start Email Automation
          </button>
        )}
        <button className="btn-secondary h-9" onClick={onOpenStatus}>
          Change Status
        </button>
        <button className="btn-secondary h-9" onClick={() => exportCampaignsCsv(selectedCampaigns)}>
          Export Report (CSV)
        </button>
        <button className="btn-ghost h-9" onClick={onClear}>
          Clear
        </button>
      </div>
    </div>
  );
}

function BulkAutomationModal({
  campaignIds,
  campaigns,
  onClose,
  onDone,
}: {
  campaignIds: string[];
  campaigns: any[];
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [shoppersPerShop, setShoppersPerShop] = useState(3);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const totalShops = campaigns.reduce((s, c) => s + (c.shops_count || 0), 0);
  const estimatedEmails = totalShops * shoppersPerShop;

  async function run() {
    setRunning(true);
    try {
      const res = await api.bulkStartAutomations(campaignIds, shoppersPerShop, true);
      setResult(res);
      toast("Bulk automation setup complete.", "success");
    } catch (e: any) {
      toast(e?.message || "Bulk automation failed", "error");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <h3 className="text-base font-bold text-slate-900 dark:text-white">Bulk-Start Email Automation</h3>
        {!result ? (
          <>
            <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
              For each shop in the {campaignIds.length} selected campaign(s), this creates an automation using the
              top AI-recommended shoppers and the default 3-step template sequence.
            </p>
            <div className="mt-4">
              <label className="label">Shoppers per shop</label>
              <input
                type="number"
                min={1}
                max={10}
                className="input w-32"
                value={shoppersPerShop}
                onChange={(e) => setShoppersPerShop(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
              />
            </div>
            <div className="mt-4 rounded-lg bg-amber-50 px-3 py-2.5 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
              ⚠ Active campaigns start immediately — up to <strong>{estimatedEmails}</strong> real emails will be
              sent via SendGrid across {totalShops} shop(s). Upcoming campaigns are created as drafts only (not sent).
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button className="btn-secondary" onClick={onClose}>Cancel</button>
              <button className="btn-primary" onClick={run} disabled={running}>
                {running ? <Spinner /> : null} Confirm & Start
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="mt-3 space-y-3">
              {result.results.map((r: any, i: number) => (
                <div key={i} className="rounded-lg border border-slate-100 p-3 text-sm dark:border-slate-800">
                  <div className="font-semibold text-slate-800 dark:text-slate-100">{r.campaign_name || r.campaign_id}</div>
                  {r.error && <div className="text-rose-500">{r.error}</div>}
                  {r.skipped && <div className="text-slate-400">Skipped — {r.reason}</div>}
                  {r.automations?.map((a: any, j: number) => (
                    <div key={j} className="mt-1 text-xs text-slate-500">
                      {a.skipped ? `${a.shop_name}: ${a.reason}` : `${a.shop_name}: ${a.shopper_count} shopper(s), ${a.started ? "started" : "created as draft"}`}
                    </div>
                  ))}
                </div>
              ))}
            </div>
            <div className="mt-5 flex justify-end">
              <button className="btn-primary" onClick={onDone}>Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function BulkStatusModal({
  campaignIds,
  campaigns,
  onClose,
  onDone,
}: {
  campaignIds: string[];
  campaigns: any[];
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [status, setStatus] = useState<"active" | "upcoming" | "completed" | "cancelled">("completed");
  const [running, setRunning] = useState(false);

  async function run() {
    setRunning(true);
    try {
      const res = await api.bulkCampaignStatus(campaignIds, status);
      toast(`Updated ${res.updated.length} campaign(s) to "${status}".`, "success");
      onDone();
    } catch (e: any) {
      toast(e?.message || "Bulk status change failed", "error");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full max-w-md rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <h3 className="text-base font-bold text-slate-900 dark:text-white">Change Status</h3>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Move {campaigns.length} selected campaign(s) to a new status. This moves them between the Active /
          Upcoming / Completed tabs — nothing is deleted.
        </p>
        <div className="mt-4">
          <label className="label">New status</label>
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value as any)}>
            <option value="active">Active</option>
            <option value="upcoming">Upcoming</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={run} disabled={running}>
            {running ? <Spinner /> : null} Apply
          </button>
        </div>
      </div>
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
        <KpiCard label="Active Campaigns" value={items.length} icon={<IconCampaign width={18} />} accent="brand" />
        <KpiCard label="Total Shops" value={totalShops} icon={<IconUsers width={18} />} accent="indigo" />
        <KpiCard label="Pending Shops" value={pending} icon={<IconClock width={18} />} accent="amber" />
        <KpiCard label="Average Progress" value={`${avgProgress}%`} icon={<IconTarget width={18} />} accent="emerald" />
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
        <KpiCard label="Upcoming Campaigns" value={items.length} icon={<IconCampaign width={18} />} accent="brand" />
        <KpiCard label="Total Shops" value={totalShops} icon={<IconUsers width={18} />} accent="indigo" />
        <KpiCard label="Required Shoppers" value={requiredShoppers} icon={<IconTarget width={18} />} accent="violet" />
        <KpiCard label="Next Start" value={next ? fmtDate(next) : "—"} icon={<IconClock width={18} />} accent="slate" />
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
      <KpiCard label="Completed Campaigns" value={items.length} icon={<IconCampaign width={18} />} accent="brand" />
      <KpiCard label="Completed Shops" value={completedShops} icon={<IconUsers width={18} />} accent="indigo" />
      <KpiCard label="Completion Rate" value={`${completionRate}%`} icon={<IconTarget width={18} />} accent="emerald" />
      <KpiCard label="Response Rate" value={`${responseRate}%`} icon={<IconClock width={18} />} accent="violet" />
    </div>
  );
}

function CampaignCard({
  c,
  tab,
  onNavigate,
  selected,
  onToggleSelect,
}: {
  c: any;
  tab: PortalTab;
  onNavigate: (path: string) => void;
  selected: boolean;
  onToggleSelect: () => void;
}) {
  const progressPct = c.total_shops ? Math.round((c.completed_shops / c.total_shops) * 100) : 0;
  const funnelData = [
    { stage: "Sent", value: c.outreach.sent },
    { stage: "Opened", value: c.outreach.opened },
    { stage: "Clicked", value: c.outreach.clicked },
    { stage: "Accepted", value: c.outreach.accepted },
  ];

  return (
    <div
      className={classNames(
        "card flex cursor-pointer flex-col p-5 transition hover:-translate-y-0.5 hover:shadow-lg",
        selected ? "ring-2 ring-brand-500" : "hover:border-brand-300 dark:hover:border-brand-700"
      )}
      onClick={() => onNavigate(`/client/campaigns/${c.id}`)}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2.5">
          <input
            type="checkbox"
            className="mt-1 h-4 w-4 shrink-0"
            checked={selected}
            onClick={(e) => e.stopPropagation()}
            onChange={onToggleSelect}
            aria-label={`Select ${c.name}`}
          />
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              {c.client_name}
            </div>
            <h3 className="text-base font-bold text-slate-900 dark:text-white">{c.name}</h3>
          </div>
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
            {c.completed_shops}/{c.total_shops} · {progressPct}%
          </span>
        </div>
        <ProgressBar value={c.completed_shops} max={c.total_shops || 1} />
      </div>

      {funnelData.some((f) => f.value > 0) ? (
        <div className="mt-4 h-20">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={funnelData} margin={{ top: 4, right: 4, bottom: 0, left: 4 }} barCategoryGap="20%">
              <Tooltip
                cursor={{ fill: "rgba(99,102,241,0.08)" }}
                contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 11, padding: "4px 8px" }}
              />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {funnelData.map((_, i) => (
                  <Cell key={i} fill={MINI_FUNNEL_COLORS[i % MINI_FUNNEL_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="mt-4 flex h-20 items-center justify-center text-xs text-slate-300 dark:text-slate-600">
          No outreach sent yet
        </div>
      )}

      <div className="mt-2 grid grid-cols-4 gap-2 text-center">
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

      <div className="mt-4 flex flex-wrap gap-2" onClick={(e) => e.stopPropagation()}>
        {tab === "active" && (
          <>
            <button className="btn-secondary" onClick={() => onNavigate(`/client/campaigns/${c.id}?tab=shops`)}>
              View Shops
            </button>
            <button className="btn-secondary" onClick={() => onNavigate(`/client/campaigns/${c.id}?tab=outreach`)}>
              Outreach
            </button>
          </>
        )}
        {tab === "upcoming" && (
          <>
            <button className="btn-secondary" onClick={() => onNavigate(`/client/campaigns/${c.id}?tab=shops`)}>
              View Shops
            </button>
            <button className="btn-secondary" onClick={() => onNavigate(`/client/campaigns/${c.id}?tab=recommendations`)}>
              AI Recommendations
            </button>
            <button className="btn-secondary" onClick={() => onNavigate(`/client/campaigns/${c.id}?tab=outreach`)}>
              Prepare Outreach
            </button>
          </>
        )}
        {tab === "completed" && (
          <>
            <button className="btn-secondary" onClick={() => onNavigate(`/client/campaigns/${c.id}?tab=shops`)}>
              View Shops
            </button>
            <button className="btn-secondary" onClick={() => onNavigate(`/client/campaigns/${c.id}?tab=overview`)}>
              View Report
            </button>
            <button className="btn-secondary" onClick={() => onNavigate(`/client/campaigns/${c.id}?tab=tracking`)}>
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
