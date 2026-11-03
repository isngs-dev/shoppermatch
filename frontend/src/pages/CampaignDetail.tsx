import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Funnel } from "../components/Funnel";
import { InvitationDrawer } from "../components/InvitationDrawer";
import { ShopperDrawer } from "../components/ShopperDrawer";
import { CampaignMapTab, ShopDetailDrawer } from "../components/ShopMap";
import { IconClock, IconMail, IconSend, IconSparkles, IconTarget, IconUsers } from "../components/Icons";
import { Avatar, Badge, CheckCell, EmptyState, KpiCard, Loading, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
import { classNames, fmtDate, fmtMoney, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

const HERO_GRADIENT: Record<string, string> = {
  active: "from-emerald-600 via-teal-600 to-brand-600",
  upcoming: "from-violet-600 via-indigo-600 to-brand-600",
  completed: "from-slate-700 via-slate-600 to-brand-700",
};

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "map", label: "Map" },
  { key: "shops", label: "Shops" },
  { key: "shoppers", label: "Shoppers" },
  { key: "recommendations", label: "AI Recommendations" },
  { key: "outreach", label: "Outreach" },
  { key: "tracking", label: "Tracking" },
  { key: "insights", label: "Insights" },
];

export function CampaignDetail({ id }: { id: string }) {
  const [params, setParams] = useSearchParams();
  const activeTab = params.get("tab") || "overview";
  const shopParam = params.get("shop") || undefined;
  const [detailShopId, setDetailShopId] = useState<string | null>(null);
  const campaign = useApi(() => api.campaign(id), [id]);

  function openRecommendationsForShop(shopId: string) {
    setDetailShopId(null);
    setParams({ tab: "recommendations", shop: shopId });
  }

  if (campaign.loading && !campaign.data) return <Loading label="Loading campaign…" />;
  if (campaign.error) return <ErrorBox message={campaign.error} onRetry={campaign.reload} />;

  const c = campaign.data;
  const pctVal = c.total_shops ? Math.round((c.completed_shops / c.total_shops) * 100) : 0;
  const bucket = c.bucket || "active";

  return (
    <div className="space-y-6">
      <div>
        <Link
          to="/client/campaigns/active"
          className="text-sm font-medium text-brand-600 hover:underline dark:text-brand-400"
        >
          ← Back to Campaigns
        </Link>
      </div>

      <div className={classNames("relative overflow-hidden rounded-2xl bg-gradient-to-br bg-gradient-size animate-gradient-x p-6 text-white shadow-glow-lg", HERO_GRADIENT[bucket] || HERO_GRADIENT.active)}>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-bold">{c.name}</h1>
              <Badge className="bg-white/20 text-white">{c.status}</Badge>
            </div>
            <p className="mt-1 text-sm text-white/80">
              {c.client_name} · Deadline {fmtDate(c.deadline)}
            </p>
          </div>
          <div className="text-right">
            <div className="text-4xl font-extrabold leading-none">{pctVal}%</div>
            <div className="mt-1 text-xs font-medium uppercase tracking-wide text-white/70">
              Progress
            </div>
          </div>
        </div>
        <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-white/20">
          <div className="h-full rounded-full bg-white transition-all" style={{ width: `${Math.min(100, pctVal)}%` }} />
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <div className="rounded-2xl transition-all duration-200 hover:-translate-y-1 hover:shadow-glow">
          <KpiCard label="Total Shops" value={c.total_shops} icon={<IconUsers width={18} />} accent="brand" />
        </div>
        <div className="rounded-2xl transition-all duration-200 hover:-translate-y-1 hover:shadow-glow">
          <KpiCard label="Completed" value={c.completed_shops} icon={<IconTarget width={18} />} accent="emerald" />
        </div>
        <div className="rounded-2xl transition-all duration-200 hover:-translate-y-1 hover:shadow-glow">
          <KpiCard label="Remaining" value={c.remaining_shops} icon={<IconClock width={18} />} accent="amber" />
        </div>
        <div className="rounded-2xl transition-all duration-200 hover:-translate-y-1 hover:shadow-glow">
          <KpiCard label="Progress" value={`${pctVal}%`} icon={<IconSend width={18} />} accent="indigo" />
        </div>
        <div className="rounded-2xl transition-all duration-200 hover:-translate-y-1 hover:shadow-glow">
          <KpiCard label="Invitations" value={c.outreach?.invitations ?? 0} icon={<IconMail width={18} />} accent="violet" />
        </div>
      </div>

      <div className="flex gap-1 overflow-x-auto rounded-xl bg-slate-100 p-1 dark:bg-slate-800/70">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setParams(t.key === "overview" ? {} : { tab: t.key })}
            className={classNames(
              "shrink-0 rounded-lg px-3.5 py-2 text-sm font-semibold transition",
              activeTab === t.key
                ? "bg-brand-600 text-white shadow"
                : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === "overview" && <OverviewTab campaign={c} />}
      {activeTab === "map" && (
        <CampaignMapTab campaignId={id} onOpenDetail={(shopId) => setDetailShopId(shopId)} />
      )}
      {activeTab === "shops" && <ShopsTab campaignId={id} />}
      {activeTab === "shoppers" && <ShoppersTab campaignId={id} />}
      {activeTab === "recommendations" && (
        <RecommendationsTab campaignId={id} campaign={c} initialShopId={shopParam} />
      )}
      {activeTab === "outreach" && <OutreachTab campaignId={id} bucket={bucket} />}
      {activeTab === "tracking" && <TrackingTab campaignId={id} />}
      {activeTab === "insights" && <InsightsTab campaignId={id} bucket={bucket} campaignName={c.name} />}

      {detailShopId && (
        <ShopDetailDrawer
          campaignId={id}
          campaignName={c.name}
          shopId={detailShopId}
          onClose={() => setDetailShopId(null)}
          onOpenRecommendations={openRecommendationsForShop}
        />
      )}
    </div>
  );
}

// ------------------------------ Overview ------------------------------ //
function OverviewTab({ campaign: c }: { campaign: any }) {
  const toast = useToast();
  const [exporting, setExporting] = useState<string | null>(null);

  async function doExport(format: "csv" | "xlsx" | "pdf") {
    setExporting(format);
    try {
      await api.exportAdminCampaignReport(c.id, format, c.name);
    } catch (e: any) {
      toast(e?.message || "Export failed", "error");
    } finally {
      setExporting(null);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="card p-5 lg:col-span-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Campaign overview
          </h2>
          <div className="flex gap-1">
            {(["pdf", "xlsx", "csv"] as const).map((fmt) => (
              <button
                key={fmt}
                className="btn-ghost !px-2 !py-1 text-xs uppercase"
                disabled={exporting === fmt}
                onClick={() => doExport(fmt)}
              >
                {exporting === fmt ? "…" : `Export ${fmt}`}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          {c.description || "No description provided."}
        </p>
        <dl className="mt-4 grid grid-cols-2 gap-4 text-sm">
          <Field label="Client" value={c.client_name} />
          <Field label="Status" value={c.status} />
          <Field label="Created" value={fmtDate(c.created_at)} />
          <Field label="Deadline" value={fmtDate(c.deadline)} />
          <Field
            label="Total shops"
            value={
              <>
                {c.total_shops ?? 0}
                <span className="ml-2 text-xs font-normal text-slate-400">
                  {c.completed_shops ?? 0} completed · {Math.max(0, (c.total_shops ?? 0) - (c.completed_shops ?? 0))} remaining
                </span>
              </>
            }
          />
        </dl>
      </div>
      <div className="card p-5">
        <h2 className="mb-4 text-sm font-semibold text-slate-800 dark:text-slate-100">
          Outreach funnel
        </h2>
        {c.outreach?.sent ? (
          <Funnel
            stages={[
              { stage: "Sent", value: c.outreach?.sent || 0 },
              { stage: "Delivered", value: c.outreach?.delivered || 0 },
              { stage: "Opened", value: c.outreach?.opened || 0 },
              { stage: "Clicked", value: c.outreach?.clicked || 0 },
              { stage: "Accepted", value: c.outreach?.accepted || 0 },
            ]}
          />
        ) : (
          <div className="flex h-40 items-center justify-center text-sm text-slate-400">
            No outreach sent yet.
          </div>
        )}
        <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-sm dark:border-slate-800">
          <span className="text-slate-500 dark:text-slate-400">Declined</span>
          <span className="font-semibold text-rose-500">{c.outreach?.declined ?? 0}</span>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <dt className="text-xs text-slate-400">{label}</dt>
      <dd className="font-semibold text-slate-800 dark:text-slate-100">{value ?? "—"}</dd>
    </div>
  );
}

// ------------------------------ Shops ------------------------------ //
const COVERAGE_COLOR: Record<string, string> = {
  healthy: "bg-emerald-500",
  medium: "bg-amber-500",
  low: "bg-rose-500",
};

function ShopsTab({ campaignId }: { campaignId: string }) {
  const { data, loading, error, reload } = useApi(() => api.campaignShops(campaignId), [campaignId]);
  if (loading && !data) return <Loading label="Loading shops…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <div className="card overflow-x-auto">
      <table className="min-w-full">
        <thead className="border-b border-slate-100 dark:border-slate-800">
          <tr>
            <th className="th">Shop</th>
            <th className="th">Location</th>
            <th className="th text-center">Required</th>
            <th className="th text-center">Invited</th>
            <th className="th">Coverage</th>
            <th className="th">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
          {data.items.map((s: any) => (
            <tr key={s.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
              <td className="td font-medium text-slate-800 dark:text-slate-100">{s.shop_name}</td>
              <td className="td text-slate-500">
                {s.city}, {s.state}
              </td>
              <td className="td text-center">{s.required_shoppers}</td>
              <td className="td text-center">{s.invited_shoppers}</td>
              <td className="td">
                <span className="inline-flex items-center gap-1.5">
                  <span className={classNames("h-2 w-2 rounded-full", COVERAGE_COLOR[s.coverage])} />
                  {s.coverage.charAt(0).toUpperCase() + s.coverage.slice(1)}
                </span>
              </td>
              <td className="td">
                <Badge className={statusBadgeClass(s.status === "open" ? "sent" : "created")}>
                  {s.status}
                </Badge>
              </td>
            </tr>
          ))}
          {data.items.length === 0 && (
            <tr>
              <td colSpan={6} className="td py-10 text-center text-slate-400">
                No shops in this campaign.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------ Shoppers ------------------------------ //
function ShoppersTab({ campaignId }: { campaignId: string }) {
  const { data, loading, error, reload } = useApi(() => api.campaignShoppers(campaignId), [campaignId]);
  if (loading && !data) return <Loading label="Loading shoppers…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <div className="card overflow-x-auto">
      <table className="min-w-full">
        <thead className="border-b border-slate-100 dark:border-slate-800">
          <tr>
            <th className="th">Shopper</th>
            <th className="th hidden md:table-cell">Location</th>
            <th className="th">Category</th>
            <th className="th">Availability</th>
            <th className="th">Invitation</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
          {data.items.map((s: any) => (
            <tr key={s.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
              <td className="td font-medium text-slate-800 dark:text-slate-100">{s.name}</td>
              <td className="td hidden text-slate-500 md:table-cell">
                {s.city}, {s.state}
              </td>
              <td className="td text-slate-500">{(s.categories || []).join(", ") || "—"}</td>
              <td className="td">
                <Badge
                  className={statusBadgeClass(s.availability_status === "available" ? "sent" : "created")}
                >
                  {s.availability_status}
                </Badge>
              </td>
              <td className="td">
                <Badge className={statusBadgeClass(s.latest_status)}>{s.latest_status}</Badge>
              </td>
            </tr>
          ))}
          {data.items.length === 0 && (
            <tr>
              <td colSpan={5} className="td py-10 text-center text-slate-400">
                No shoppers invited to this campaign yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------ AI Recommendations ------------------------------ //
const CLASS_META: Record<string, { label: string; badge: string }> = {
  TOP_MATCH: { label: "TOP MATCH", badge: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300" },
  STRONG_MATCH: { label: "STRONG MATCH", badge: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300" },
  POTENTIAL_MATCH: { label: "POTENTIAL MATCH", badge: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300" },
  LOW_MATCH: { label: "LOW MATCH", badge: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400" },
};

const AVAIL_META: Record<string, string> = {
  available: "✓ Available",
  limited: "⚠ Limited Availability",
  busy: "⚠ Limited Availability",
  unavailable: "✕ Unavailable",
};

// How a shop stands for staffing — decided by the backend (services/staffing.py) so every campaign and shop
// follows the same rule: filled → ready (the AI found exactly who's needed) → short (it couldn't, so widen
// the radius and then recommend a bonus).
const STAFFING_STYLE: Record<string, { card: string; dot: string; pill: string; label: string }> = {
  filled: {
    card: "border-emerald-200 dark:border-emerald-900",
    dot: "bg-emerald-500",
    pill: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    label: "Fully staffed",
  },
  ready: {
    card: "border-indigo-200 dark:border-indigo-900",
    dot: "bg-indigo-500",
    pill: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300",
    label: "AI recommendation ready",
  },
  short: {
    card: "border-amber-200 dark:border-amber-900",
    dot: "bg-amber-500",
    pill: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
    label: "Recruitment gap",
  },
};

function RecommendationsTab({
  campaignId,
  campaign,
  initialShopId,
}: {
  campaignId: string;
  campaign: any;
  initialShopId?: string;
}) {
  const navigate = useNavigate();
  const shops = useApi(() => api.campaignShops(campaignId), [campaignId]);
  const [shopId, setShopId] = useState("");
  const [radius, setRadius] = useState(25);
  // How many times the radius was widened for this shop — a bonus is recommended once widening was tried
  // (or can't help) and the shop is still short.
  const [widened, setWidened] = useState(0);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  // "recommended" = exactly the shoppers this shop still needs. "more" (the rest of the ranked pool, for
  // over-selection) can only be opened once the AI has recommended everyone the shop needs.
  const [view, setView] = useState<"recommended" | "more">("recommended");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [breakdownFor, setBreakdownFor] = useState<any | null>(null);
  const [profileFor, setProfileFor] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [togglingOverSelection, setTogglingOverSelection] = useState(false);
  const [bonusShop, setBonusShop] = useState<any | null>(null);
  const [bonusSuggestion, setBonusSuggestion] = useState<{ amount: number; note: string } | null>(null);
  // Bumped whenever a bonus is saved, so Auto Assign re-runs and picks up the shoppers the bonus now reaches.
  const [bonusVersion, setBonusVersion] = useState(0);
  const toast = useToast();

  const shopDetail = useApi(() => (shopId ? api.shop(shopId) : Promise.resolve(null)), [shopId]);

  async function toggleOverSelection(allow: boolean) {
    if (!shopId) return;
    setTogglingOverSelection(true);
    try {
      await api.setShopOverSelection(shopId, allow);
      await shopDetail.reload();
      toast(allow ? "Over-selection enabled for this shop." : "Over-selection disabled — selection is capped at the required count again.", "success");
    } catch (e: any) {
      toast(e?.message || "Failed to update over-selection setting", "error");
    } finally {
      setTogglingOverSelection(false);
    }
  }

  useEffect(() => {
    if (shops.data && !shopId) {
      const preferred = initialShopId && shops.data.items.some((s: any) => s.id === initialShopId);
      setShopId(preferred ? initialShopId! : shops.data.items[0]?.id || "");
    }
  }, [shops.data]);

  useEffect(() => {
    // Selected shop changed — start fresh (spec §22/23) and analyze this shop's eligible shoppers right away
    // so the AI recommendation is always there without a manual click.
    setResult(null);
    setSelected(new Set());
    setView("recommended");
    setRadius(25);
    setWidened(0);
    if (shopId) {
      runMatching(25);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shopId]);

  const selectedShop = shops.data?.items.find((s: any) => s.id === shopId);

  // Takes the radius explicitly so a caller that just changed it (Expand Search Radius) re-runs with the new
  // value instead of the `radius` state, which hasn't committed yet inside the same handler.
  async function runMatching(radiusOverride?: number): Promise<any | null> {
    if (!shopId) return null;
    setRunning(true);
    setRunError(null);
    try {
      const r = await api.aiShopRecommendations(campaignId, shopId, { limit: 20, radius: radiusOverride ?? radius });
      setResult(r);
      // Start with the AI's exact recommendation pre-ticked, so approving fills the shop in one click.
      setSelected(new Set<string>((r.recommendations || []).filter((x: any) => x.recommended).map((x: any) => x.shopper_id)));
      setView("recommended");
      return r;
    } catch (e: any) {
      setRunError(e?.message || "AI matching failed");
      return null;
    } finally {
      setRunning(false);
    }
  }

  // The backend says which radius actually reaches more shoppers (never past a visitable distance).
  async function expandRadius(to?: number) {
    const next = to ?? radius + 25;
    setRadius(next);
    setWidened((n) => n + 1);
    const r = await runMatching(next);
    if (!r) return;
    const st = r.staffing;
    if (st.state !== "short") {
      toast(`Widening to ${next} km found everyone this shop needs.`, "success");
    } else if (st.recruit_locally) {
      toast(`Still short at ${next} km and nobody else is within visiting distance — recruit shoppers near this shop.`, "info");
    } else if (st.bonus_recommended) {
      toast(`Still short at ${next} km — the AI recommends adding a bonus to attract shoppers.`, "info");
    }
  }

  function openBonus(suggestion?: { amount: number; note: string } | null) {
    setBonusSuggestion(suggestion ?? null);
    setBonusShop(selectedShop);
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function outreachUrl() {
    const type = campaign.bucket === "upcoming" ? "upcoming" : "active";
    return `/client/outreach?campaign=${campaignId}&shop=${shopId}&type=${type}`;
  }

  async function approveAndGoToOutreach() {
    if (!shopId || selected.size === 0) return;
    setApproving(true);
    try {
      const res = await api.approveAiRecommendations(campaignId, shopId, Array.from(selected));
      toast(`Approved ${res.count} shopper(s) — sending you to Outreach to email them.`, "success");
      navigate(outreachUrl());
    } catch (e: any) {
      toast(e?.message || "Failed to approve recommendations", "error");
    } finally {
      setApproving(false);
    }
  }

  if (shops.loading && !shops.data) return <Loading label="Loading shops…" />;
  if (!shops.data?.items?.length)
    return (
      <div className="card">
        <EmptyState title="No shops to recommend against" hint="Add shops to this campaign first." />
      </div>
    );

  const required = selectedShop?.required_shoppers ?? 0;
  const staffing = result?.staffing;
  const all: any[] = result?.recommendations || [];
  const recommendedList = all.filter((r) => r.recommended);
  const moreList = all.filter((r) => !r.recommended && !r.already_invited);
  const alreadyList = all.filter((r) => r.already_invited);
  // "More candidates" only exists once the shop has what it needs (all recommended, or already staffed).
  const canShowMore = !!staffing && staffing.state !== "short" && moreList.length > 0;
  const visible = view === "more" && canShowMore ? moreList : recommendedList;
  const stillNeeded = staffing?.slots_open ?? selectedShop?.open_slots ?? required;
  const selectedCount = staffing?.already_selected ?? selectedShop?.selected_shoppers ?? 0;
  const allowOverSelection = !!shopDetail.data?.allow_over_selection;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-bold text-slate-900 dark:text-white">AI Shopper Recommendations</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Pick a shop. The AI recommends exactly the shoppers it still needs — if it can't find enough, it helps you
          close the gap.
        </p>
      </div>

      {/* 1 — which shop, and where it stands */}
      <div className="card p-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-[16rem] flex-1">
            <label className="label">Shop</label>
            <select className="input" value={shopId} onChange={(e) => setShopId(e.target.value)}>
              {shops.data.items.map((s: any) => (
                <option key={s.id} value={s.id}>
                  {s.shop_name} — {s.open_slots === 0 ? "✓ filled" : `needs ${s.open_slots} more`}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-4 gap-2 text-center">
            <ShopStat label="Required" value={required} />
            <ShopStat label="Selected" value={selectedCount} />
            <ShopStat label="Still needed" value={stillNeeded} accent={stillNeeded > 0 ? "text-amber-600 dark:text-amber-400" : "text-emerald-600 dark:text-emerald-400"} />
            <ShopStat
              label="Radius"
              value={`${radius} km`}
              hint={staffing?.bonus_reach_km > 0 ? `+${staffing.bonus_reach_km.toLocaleString()} km from bonus` : undefined}
            />
          </div>
        </div>
        {selectedShop && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3 text-xs dark:border-slate-800">
            <span className="text-slate-500 dark:text-slate-400">
              {selectedShop.bonus ? (
                <>
                  💰 Bonus {fmtMoney(selectedShop.bonus.amount, selectedShop.bonus.currency)}
                  {selectedShop.bonus.completed_at
                    ? ` — awarded to ${selectedShop.bonus.awarded_shopper_name || "shopper"}`
                    : " — pending, funded by you, paid outside ShopperMatch"}
                </>
              ) : (
                "No bonus set for this shop."
              )}
            </span>
            <button className="font-semibold text-brand-600 hover:underline dark:text-brand-400" onClick={() => openBonus()}>
              {selectedShop.bonus ? "Edit bonus" : "+ Add bonus"}
            </button>
          </div>
        )}
      </div>

      {running && !result && (
        <div className="card">
          <EmptyState title="Analyzing…" hint="AI matching runs automatically whenever you select a shop." />
        </div>
      )}
      {runError && <ErrorBox message={runError} onRetry={() => runMatching()} />}

      {/* 2 — what to do next, by state */}
      {result && staffing && (
        <StaffingCard
          staffing={staffing}
          shopName={selectedShop?.shop_name || result.shop_name}
          radius={radius}
          widened={widened}
          running={running}
          approving={approving}
          selectedCount={selected.size}
          alreadyNames={alreadyList.map((r) => r.name)}
          moreCount={canShowMore ? moreList.length : 0}
          showingMore={view === "more"}
          shopCity={[selectedShop?.city, selectedShop?.state].filter(Boolean).join(", ")}
          existingBonus={selectedShop?.bonus ?? null}
          onExpand={() => expandRadius(staffing.next_radius_km ?? undefined)}
          onAddBonus={() => openBonus(staffing.suggested_bonus)}
          onApprove={approveAndGoToOutreach}
          onGoToOutreach={() => navigate(outreachUrl())}
          onShowMore={() => setView("more")}
          onShowRecommended={() => setView("recommended")}
        />
      )}

      {/* 3 — the shoppers */}
      {/* Nothing to list when the shop is staffed, or short with nobody found — the card above already says so. */}
      {result && staffing && (view === "more" || (staffing.state !== "filled" && recommendedList.length > 0)) && (
        <>
          {view === "more" && (
            <div className="card flex flex-wrap items-center justify-between gap-3 border border-indigo-200 p-4 dark:border-indigo-900">
              <p className="max-w-xl text-sm text-slate-600 dark:text-slate-300">
                {selectedShop?.shop_name || "This shop"} has what it needs ({required}). These are extra shoppers you can add
                as backups{allowOverSelection ? " — over-selection is on for this shop." : " once over-selection is on."}
              </p>
              <button
                className={allowOverSelection ? "btn-secondary" : "btn-primary"}
                onClick={() => toggleOverSelection(!allowOverSelection)}
                disabled={togglingOverSelection}
              >
                {togglingOverSelection ? <Spinner /> : null}{" "}
                {allowOverSelection ? "Turn off over-selection" : "Allow over-selection"}
              </button>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              {view === "more" ? `More candidates (${moreList.length})` : `Recommended shoppers (${recommendedList.length})`}
            </div>
            {visible.length > 1 && (
              <div className="flex gap-2 text-[11px]">
                <button
                  type="button"
                  className="font-semibold text-brand-600 hover:underline dark:text-brand-400"
                  onClick={() => setSelected(new Set(visible.map((r: any) => r.shopper_id)))}
                >
                  Select all
                </button>
                <button type="button" className="font-semibold text-slate-400 hover:underline" onClick={() => setSelected(new Set())}>
                  Deselect all
                </button>
              </div>
            )}
          </div>

          {visible.length === 0 ? (
            <div className="card">
              <EmptyState
                title={view === "more" ? "No more candidates" : "No shoppers to recommend yet"}
                hint="Widen the search radius or add a bonus below to reach more shoppers."
              />
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              {visible.map((r: any, i: number) => (
                <CandidateCard
                  key={r.shopper_id}
                  r={r}
                  rank={i + 1}
                  checked={selected.has(r.shopper_id)}
                  onToggle={() => toggleSelect(r.shopper_id)}
                  onBreakdown={() => setBreakdownFor(r)}
                  onViewProfile={() => setProfileFor(r.shopper_id)}
                />
              ))}
            </div>
          )}
        </>
      )}

      {selected.size > 0 && (() => {
        const alreadySelected = shopDetail.data?.active_selected_count ?? selectedCount;
        const wouldExceed = !allowOverSelection && required > 0 && alreadySelected + selected.size > required;
        const remaining = Math.max(0, required - alreadySelected);
        return (
          <div className="card sticky bottom-4 flex flex-wrap items-center justify-between gap-3 p-4">
            <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              Selected: {selected.size} / {required} required
              {alreadySelected > 0 && (
                <span className="ml-1 font-normal text-slate-400">({alreadySelected} already selected for this shop)</span>
              )}
              {wouldExceed && (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs font-normal text-amber-600 dark:text-amber-400">
                  <span>Over-selection is off — only {remaining} more can be approved for this shop.</span>
                  <button
                    className="font-semibold underline disabled:opacity-50"
                    onClick={() => toggleOverSelection(true)}
                    disabled={togglingOverSelection}
                  >
                    Allow over-selection for this shop
                  </button>
                </div>
              )}
              {allowOverSelection && (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs font-normal text-emerald-600 dark:text-emerald-400">
                  <span>Over-selection is allowed for this shop.</span>
                  <button
                    className="font-semibold underline disabled:opacity-50"
                    onClick={() => toggleOverSelection(false)}
                    disabled={togglingOverSelection}
                  >
                    Turn off
                  </button>
                </div>
              )}
            </div>
            <button className="btn-primary" onClick={approveAndGoToOutreach} disabled={approving || wouldExceed}>
              {approving ? <Spinner /> : null} Approve &amp; Go to Outreach
            </button>
          </div>
        );
      })()}

      {/* 4 — how the AI got there (collapsed: not needed to act) */}
      {result && (
        <details className="card group p-5">
          <summary className="cursor-pointer select-none text-sm font-semibold text-slate-800 dark:text-slate-100">
            How the AI analyzed this shop
          </summary>
          <p className="mt-3 text-sm italic text-slate-700 dark:text-slate-200">"{result.requirement_summary}"</p>
          <div className="mt-2 text-xs text-slate-400">
            Found {result.total_candidates} candidate shoppers · {result.eligible_count} eligible · {result.excluded.unavailable}{" "}
            unavailable · {result.excluded.inactive} inactive
            {result.excluded.outside_radius ? ` · ${result.excluded.outside_radius} outside ${radius} km radius` : ""}
            {result.excluded.requirements_not_met ? ` · ${result.excluded.requirements_not_met} don't meet campaign requirements` : ""}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-5">
            <MiniStat label="Analyzed" value={result.total_candidates} />
            <MiniStat label="Eligible" value={result.eligible_count} />
            <MiniStat label="Top" value={result.classification_counts.top_match} accent="text-emerald-600 dark:text-emerald-400" />
            <MiniStat label="Strong" value={result.classification_counts.strong_match} accent="text-indigo-600 dark:text-indigo-400" />
            <MiniStat label="Potential" value={result.classification_counts.potential_match} accent="text-amber-600 dark:text-amber-400" />
          </div>
        </details>
      )}

      {/* 5 — the whole campaign at once */}
      <AutoAssignCard
        campaignId={campaignId}
        shops={shops.data?.items || []}
        onOpenShop={(id) => {
          setShopId(id);
          window.scrollTo({ top: 0, behavior: "smooth" });
        }}
        onAddBonus={(id, suggestion) => {
          setBonusSuggestion(suggestion ?? null);
          setBonusShop(shops.data?.items.find((s: any) => s.id === id) ?? null);
        }}
        rerunToken={bonusVersion}
        onApproved={() =>
          navigate(`/client/outreach?campaign=${campaignId}&type=${campaign.bucket === "upcoming" ? "upcoming" : "active"}&view=approved`)
        }
      />

      {breakdownFor && <BreakdownModal r={breakdownFor} shopId={shopId} onClose={() => setBreakdownFor(null)} />}
      {profileFor && <ShopperDrawer shopperId={profileFor} onClose={() => setProfileFor(null)} />}
      {bonusShop && (
        <BonusModal
          shop={bonusShop}
          campaignId={campaignId}
          suggestion={bonusSuggestion}
          onClose={() => {
            setBonusShop(null);
            setBonusSuggestion(null);
          }}
          onSaved={() => {
            shops.reload();
            setBonusVersion((v) => v + 1);
            // The recommendation depends on the bonus (a raised one is no longer re-suggested), so refresh it.
            if (bonusShop?.id === shopId) runMatching();
          }}
        />
      )}
    </div>
  );
}

function ShopStat({ label, value, accent, hint }: { label: string; value: string | number; accent?: string; hint?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800/60">
      <div className={classNames("text-base font-bold text-slate-900 dark:text-white", accent)}>{value}</div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      {hint && <div className="text-[10px] font-medium text-indigo-500 dark:text-indigo-400">{hint}</div>}
    </div>
  );
}

// The one card that tells the client what to do next for this shop.
function StaffingCard({
  staffing,
  shopName,
  radius,
  widened,
  running,
  approving,
  selectedCount,
  alreadyNames,
  moreCount,
  showingMore,
  shopCity,
  existingBonus,
  onExpand,
  onAddBonus,
  onApprove,
  onGoToOutreach,
  onShowMore,
  onShowRecommended,
}: {
  staffing: any;
  shopName: string;
  radius: number;
  widened: number;
  running: boolean;
  approving: boolean;
  selectedCount: number;
  alreadyNames: string[];
  moreCount: number;
  showingMore: boolean;
  shopCity: string;
  existingBonus: { amount: number; currency: string } | null;
  onExpand: () => void;
  onAddBonus: () => void;
  onApprove: () => void;
  onGoToOutreach: () => void;
  onShowMore: () => void;
  onShowRecommended: () => void;
}) {
  const style = STAFFING_STYLE[staffing.state];
  const bonus = staffing.suggested_bonus;
  // Widening the radius comes first; the bonus is the next recommendation once that was tried (or can't help).
  const showBonus = staffing.bonus_recommended && (widened > 0 || !staffing.can_expand_radius);

  return (
    <div className={classNames("card border p-5", style.card)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={classNames("h-2.5 w-2.5 rounded-full", style.dot)} />
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
            {staffing.state === "filled" && `${shopName} is fully staffed — ${staffing.already_selected} of ${staffing.required} selected`}
            {staffing.state === "ready" &&
              `AI recommends ${staffing.slots_open} shopper${staffing.slots_open === 1 ? "" : "s"} for ${shopName}`}
            {staffing.state === "short" &&
              `AI found ${staffing.recommended} of ${staffing.slots_open} shopper${staffing.slots_open === 1 ? "" : "s"} needed`}
          </h3>
        </div>
        <span className={classNames("rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide", style.pill)}>
          {style.label}
        </span>
      </div>

      {staffing.state === "filled" && (
        <>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            {alreadyNames.length > 0 ? `Selected: ${alreadyNames.join(", ")}. ` : ""}Nothing more to recommend — send the
            invitations from Outreach.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn-primary" onClick={onGoToOutreach}>
              Go to Outreach →
            </button>
            {moreCount > 0 && !showingMore && (
              <button className="btn-secondary" onClick={onShowMore}>
                Need backup shoppers? View more candidates ({moreCount})
              </button>
            )}
          </div>
        </>
      )}

      {staffing.state === "ready" && (
        <>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            Exactly the {staffing.slots_open} this shop still needs — already ticked below. Approve them and the invitations are
            ready to send from Outreach.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button className="btn-primary" onClick={onApprove} disabled={approving || selectedCount === 0}>
              {approving ? <Spinner /> : null} Approve {selectedCount} &amp; Go to Outreach
            </button>
            {moreCount > 0 &&
              (showingMore ? (
                <button className="btn-secondary" onClick={onShowRecommended}>
                  ← Back to recommended
                </button>
              ) : (
                <button className="btn-secondary" onClick={onShowMore}>
                  Need more than {staffing.slots_open}? View more candidates ({moreCount})
                </button>
              ))}
          </div>
        </>
      )}

      {staffing.state === "short" && (
        <>
          <div className="mt-3 grid grid-cols-4 gap-3 text-sm">
            <GapFigure label="Required" value={staffing.required} />
            <GapFigure label="Already selected" value={staffing.already_selected} />
            <GapFigure label="AI found" value={staffing.recommended} />
            <GapFigure label="Gap" value={`${staffing.shortfall} shopper(s)`} accent="text-rose-600 dark:text-rose-400" />
          </div>
          {staffing.reason && <p className="mt-3 text-sm text-slate-600 dark:text-slate-400">{staffing.reason}</p>}

          <ol className="mt-4 space-y-3">
            <li className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">1 · Widen the search</div>
              {staffing.can_expand_radius ? (
                <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {staffing.far && staffing.nearest_outside_km != null
                      ? `The nearest other shoppers are ${Math.round(staffing.nearest_outside_km).toLocaleString()} km away — a long trip for a store visit. Widening to ${staffing.next_radius_km} km reaches them anyway.`
                      : `Shoppers are just outside ${radius} km — widening to ${staffing.next_radius_km} km reaches them.`}
                  </p>
                  <button className="btn-secondary" onClick={onExpand} disabled={running}>
                    {running ? <Spinner /> : null} Expand to {staffing.next_radius_km} km
                  </button>
                </div>
              ) : (
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {staffing.nearest_outside_km != null
                    ? `The nearest other shopper is ${Math.round(staffing.nearest_outside_km).toLocaleString()} km away — too far for a store visit, so widening won't help.`
                    : "Nobody else matches this shop, so widening the radius would not add anyone."}
                </p>
              )}
            </li>

            <li
              className={classNames(
                "rounded-lg border p-3",
                showBonus
                  ? "border-indigo-200 bg-indigo-50 dark:border-indigo-900 dark:bg-indigo-950/30"
                  : "border-slate-200 dark:border-slate-800"
              )}
            >
              <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">2 · Add a bonus to attract shoppers</div>
              {showBonus && bonus ? (
                <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
                  <p className="max-w-xl text-sm text-indigo-800 dark:text-indigo-300">
                    🤖{" "}
                    <span className="font-semibold">
                      AI recommends {bonus.raises_existing ? "raising the bonus to" : "a"} {fmtMoney(bonus.amount, bonus.currency)}
                      {bonus.raises_existing ? "" : " bonus"}
                    </span>{" "}
                    — {widened > 0 ? `even at ${radius} km the shop is still short` : "the shop is short"}.{" "}
                    {bonus.fills_gap
                      ? `It pays for the trip, so shoppers up to ${Math.round(radius + bonus.reach_km).toLocaleString()} km away qualify — enough to fill this shop.`
                      : "It helps, but on its own it won't reach enough shoppers — widen the radius too."}
                  </p>
                  <button className="btn-primary shrink-0" onClick={onAddBonus}>
                    {bonus.raises_existing ? `Raise Bonus to ${fmtMoney(bonus.amount, bonus.currency)}` : "Add Suggested Bonus"}
                  </button>
                </div>
              ) : existingBonus && (staffing.bonus_maxed || staffing.recruit_locally) ? (
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  A {fmtMoney(existingBonus.amount, existingBonus.currency)} bonus is already set.{" "}
                  {staffing.bonus_maxed
                    ? "That is the most the AI would recommend — more money won't add shoppers."
                    : "There is nobody within visiting distance to tempt, so raising it won't help."}
                </p>
              ) : (
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  If widening the radius still leaves {shopName} short, the AI will recommend a bonus here.
                </p>
              )}
            </li>

            {staffing.recruit_locally && (
              <li className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-900 dark:bg-emerald-950/30">
                <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                  3 · Recruit shoppers near {shopCity || shopName}
                </div>
                <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
                  <p className="max-w-xl text-sm text-emerald-800 dark:text-emerald-300">
                    This shop can only be filled by shoppers who live near it. Post a region-targeted recruitment ad so local
                    shoppers sign up — they show up here as soon as they do.
                  </p>
                  <Link className="btn-primary shrink-0" to="/client/social-media">
                    Recruit via Social Media
                  </Link>
                </div>
              </li>
            )}
          </ol>

          {staffing.recommended > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3 dark:border-slate-800">
              <button className="btn-secondary" onClick={onApprove} disabled={approving || selectedCount === 0}>
                {approving ? <Spinner /> : null} Approve the {selectedCount} found &amp; Go to Outreach
              </button>
              <span className="text-xs text-slate-400">You can start inviting now and keep closing the gap.</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function GapFigure({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
  return (
    <div>
      <div className="text-xs text-slate-400">{label}</div>
      <div className={classNames("font-semibold text-slate-800 dark:text-slate-100", accent)}>{value}</div>
    </div>
  );
}

// Client-funded bonus money for a shop that isn't filled yet (see
// backend/app/models.py::ShopBonus). ShopperMatch never processes this
// payment — it just tracks the pledge and, once ISN marks the shop
// completed, emails a reminder to pay whichever shopper did it.
function BonusModal({
  shop,
  campaignId,
  suggestion,
  onClose,
  onSaved,
}: {
  shop: any;
  campaignId: string;
  suggestion?: { amount: number; note: string } | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const existing = shop.bonus;
  // A suggestion wins over the saved bonus: when the AI says a bonus is too low, it opens pre-filled with the raise.
  const [amount, setAmount] = useState(suggestion ? String(suggestion.amount) : existing ? String(existing.amount) : "");
  const [note, setNote] = useState(existing?.note || suggestion?.note || "");
  const [busy, setBusy] = useState(false);
  const awarded = !!existing?.completed_at;

  async function save() {
    const n = Number(amount);
    if (!n || n <= 0) {
      toast("Enter a bonus amount greater than 0", "error");
      return;
    }
    setBusy(true);
    try {
      await api.setShopBonus(campaignId, shop.id, Math.round(n), note.trim() || undefined);
      toast(`Bonus of ${fmtMoney(Math.round(n), shop.currency)} set for ${shop.shop_name}`, "success");
      onSaved();
      onClose();
    } catch (e: any) {
      toast(e?.message || "Failed to save bonus", "error");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api.removeShopBonus(campaignId, shop.id);
      toast(`Bonus removed for ${shop.shop_name}`, "success");
      onSaved();
      onClose();
    } catch (e: any) {
      toast(e?.message || "Failed to remove bonus", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full max-w-sm rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-900 dark:text-white">
            {existing ? "Edit Bonus" : "Add Bonus"} — {shop.shop_name}
          </h3>
          <button className="btn-ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {suggestion && !awarded && (
          <p className="mt-2 text-xs font-medium text-indigo-600 dark:text-indigo-400">
            🤖 Amount pre-filled from the AI's suggestion — edit it before saving.
          </p>
        )}
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          Extra incentive on top of standard compensation, funded and paid by you directly to the shopper —
          ShopperMatch does not process this payment. Whichever shopper completes this shop receives it, and
          you'll get an email reminder once ISN confirms the shop is done.
        </p>

        {awarded ? (
          <div className="mt-4 rounded-lg bg-teal-50 px-3 py-2 text-sm text-teal-700 dark:bg-teal-950/40 dark:text-teal-300">
            This bonus was already awarded to {existing.awarded_shopper_name || "a shopper"} and can no longer be
            edited.
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            <div>
              <label className="label">Bonus amount ({shop.currency})</label>
              <input
                className="input"
                type="number"
                min={1}
                autoFocus
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="e.g. 500"
              />
            </div>
            <div>
              <label className="label">Note (optional)</label>
              <input
                className="input"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. For a same-week visit"
              />
            </div>
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          {existing && !awarded && (
            <button className="btn-secondary mr-auto text-rose-600 dark:text-rose-400" onClick={remove} disabled={busy}>
              Remove
            </button>
          )}
          <button className="btn-secondary" onClick={onClose}>
            {awarded ? "Close" : "Cancel"}
          </button>
          {!awarded && (
            <button className="btn-primary" onClick={save} disabled={busy}>
              {busy ? <Spinner /> : null} Save Bonus
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function AutoAssignCard({
  campaignId,
  shops,
  onOpenShop,
  onAddBonus,
  onApproved,
  rerunToken,
}: {
  campaignId: string;
  shops: any[];
  onOpenShop?: (shopId: string) => void;
  onAddBonus?: (shopId: string, suggestion: { amount: number; note: string } | null) => void;
  // Called once every proposed assignment became a real invitation — the page sends the client on to Outreach.
  onApproved?: () => void;
  // Bumped by the page after a bonus is saved: the proposal is re-run so the bonus's reach shows up in it.
  rerunToken?: number;
}) {
  const toast = useToast();
  const bonusByShopId = useMemo(() => {
    const map = new Map<string, any>();
    for (const s of shops) if (s.bonus) map.set(s.id, s.bonus);
    return map;
  }, [shops]);
  // Kept as raw text while typing (not a number) so backspacing to clear
  // the field doesn't immediately snap back to a forced value — only
  // clamped to a real number where it's actually used, below.
  const [radiusInput, setRadiusInput] = useState("25");
  const radius = Math.max(1, parseInt(radiusInput, 10) || 25);
  const [optimizing, setOptimizing] = useState(false);
  const [proposal, setProposal] = useState<any | null>(null);
  const [approving, setApproving] = useState(false);
  // Shops the over-selection cap blocked, keyed by shop id — kept around
  // (rather than aborting the whole approve on the first one) so every
  // OTHER shop's assignment still goes through, and the client can enable
  // over-selection + retry just the shops that actually need it.
  const [blocked, setBlocked] = useState<Record<string, { shopName: string; shopperIds: string[]; message: string }>>({});
  // Shops already turned into real invitations — approveAll skips these on
  // a retry pass so re-clicking "Retry Remaining" never double-creates
  // invitations for shops that already succeeded.
  const [approvedShopIds, setApprovedShopIds] = useState<Set<string>>(new Set());
  const [retrying, setRetrying] = useState<string | null>(null);
  // Radius overrides for shops that came up short and were widened on their own (shop id → km).
  const [shopRadii, setShopRadii] = useState<Record<string, number>>({});

  async function optimize(radii: Record<string, number> = shopRadii) {
    setOptimizing(true);
    try {
      const res = await api.aiOptimizeAssignments(campaignId, radius, radii);
      setProposal(res);
      setBlocked({});
      setApprovedShopIds(new Set());
    } catch (e: any) {
      toast(e?.message || "Failed to optimize assignments", "error");
    } finally {
      setOptimizing(false);
    }
  }

  // Widen the given unfilled shops to the radius that reaches their shoppers, then re-run the analysis. With
  // several rounds it keeps going while that still fills slots: shoppers one shop reaches may already be taken by
  // another, so the next round looks further, until the campaign is staffed or nobody else is left to reach.
  async function widenShops(unfilled: any[], rounds = 1) {
    const radii = { ...shopRadii };
    let list = unfilled;
    let lastSlots = proposal ? proposal.unfilled.reduce((n: number, u: any) => n + u.unfilled_slots, 0) : Infinity;
    setOptimizing(true);
    try {
      let res: any = proposal;
      for (let round = 0; round < rounds; round++) {
        for (const u of list) if (u.next_radius_km) radii[u.shop_id] = u.next_radius_km;
        res = await api.aiOptimizeAssignments(campaignId, radius, radii);
        const slots = res.unfilled.reduce((n: number, u: any) => n + u.unfilled_slots, 0);
        list = res.unfilled.filter((u: any) => u.can_expand_radius);
        if (!list.length || slots >= lastSlots) break;
        lastSlots = slots;
      }
      setShopRadii(radii);
      setProposal(res);
      setBlocked({});
      setApprovedShopIds(new Set());
    } catch (e: any) {
      toast(e?.message || "Failed to widen the search", "error");
    } finally {
      setOptimizing(false);
    }
  }

  useEffect(() => {
    if (rerunToken && proposal) optimize();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rerunToken]);

  async function approveAll() {
    if (!proposal) return;
    setApproving(true);
    try {
      const byShop = new Map<string, { shopName: string; shopperIds: string[] }>();
      for (const p of proposal.proposals) {
        if (approvedShopIds.has(p.shop_id)) continue;
        const entry = byShop.get(p.shop_id) || { shopName: p.shop_name, shopperIds: [] as string[] };
        entry.shopperIds.push(p.shopper_id);
        byShop.set(p.shop_id, entry);
      }
      let totalCreated = 0;
      const nowBlocked: typeof blocked = {};
      const newlyApproved: string[] = [];
      for (const [shopId, { shopName, shopperIds }] of byShop) {
        try {
          const res = await api.approveAiRecommendations(campaignId, shopId, shopperIds);
          totalCreated += res.count;
          newlyApproved.push(shopId);
        } catch (e: any) {
          nowBlocked[shopId] = { shopName, shopperIds, message: e?.message || "Failed to approve this shop's assignment" };
        }
      }
      setBlocked(nowBlocked);
      if (newlyApproved.length) {
        setApprovedShopIds((prev) => new Set([...prev, ...newlyApproved]));
      }
      const blockedCount = Object.keys(nowBlocked).length;
      if (totalCreated > 0) {
        toast(
          `Approved ${totalCreated} assignment(s) — now available in Outreach.` +
            (blockedCount ? ` ${blockedCount} shop(s) need over-selection enabled first.` : ""),
          blockedCount ? "info" : "success"
        );
      } else if (blockedCount) {
        toast(`${blockedCount} shop(s) need over-selection enabled first — see below.`, "error");
      }
      if (blockedCount === 0) {
        setProposal(null);
        // Everything is approved — the next step is emailing those shoppers, so go straight to Outreach.
        if (totalCreated > 0 || approvedShopIds.size > 0) onApproved?.();
      }
    } finally {
      setApproving(false);
    }
  }

  async function enableOverSelectionAndRetry(shopId: string) {
    const entry = blocked[shopId];
    if (!entry) return;
    setRetrying(shopId);
    try {
      await api.setShopOverSelection(shopId, true);
      const res = await api.approveAiRecommendations(campaignId, shopId, entry.shopperIds);
      setBlocked((prev) => {
        const next = { ...prev };
        delete next[shopId];
        return next;
      });
      setApprovedShopIds((prev) => new Set([...prev, shopId]));
      toast(`Over-selection enabled for ${entry.shopName} — approved ${res.count} shopper(s).`, "success");
    } catch (e: any) {
      toast(e?.message || "Still failed to approve this shop", "error");
    } finally {
      setRetrying(null);
    }
  }

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">AI Assignment Optimization</h3>
          <p className="text-xs text-slate-400">Finds the best shopper-to-shop assignment across this whole campaign.</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="label">Search radius (km)</label>
            <input
              type="number"
              min={1}
              className="input h-9 w-28"
              value={radiusInput}
              onChange={(e) => setRadiusInput(e.target.value)}
            />
          </div>
          <button className="btn-secondary" onClick={() => optimize()} disabled={optimizing}>
            {optimizing ? <Spinner /> : <IconSparkles width={16} height={16} />}
            {optimizing ? "Analyzing…" : proposal ? "🔄 Re-run Analysis" : "Auto Assign Shoppers"}
          </button>
        </div>
      </div>

      {proposal && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-3 gap-3 text-center">
            <MiniStat label="Coverage" value={proposal.summary.coverage} accent="text-emerald-600 dark:text-emerald-400" />
            <MiniStat label="Requirement Satisfaction" value={proposal.summary.requirement_satisfaction} accent="text-indigo-600 dark:text-indigo-400" />
            <MiniStat label="Avg Distance (km)" value={proposal.summary.average_distance_km ?? 0} accent="text-slate-700 dark:text-slate-200" />
          </div>
          {Object.keys(shopRadii).length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
              <span>{Object.keys(shopRadii).length} shop(s) are using a widened radius.</span>
              <button
                className="font-semibold text-brand-600 hover:underline dark:text-brand-400"
                onClick={() => {
                  setShopRadii({});
                  optimize({});
                }}
              >
                Reset to {radius} km
              </button>
            </div>
          )}
          <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
            <table className="min-w-full text-sm">
              <thead className="border-b border-slate-100 dark:border-slate-800">
                <tr>
                  <th className="th">Shop</th>
                  <th className="th">Assigned Shopper</th>
                  <th className="th text-right">Match Score</th>
                  <th className="th text-right">Distance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
                {proposal.proposals.map((p: any, i: number) => {
                  const bonus = bonusByShopId.get(p.shop_id);
                  return (
                  <tr key={i}>
                    <td className="td">
                      {p.shop_name}
                      {bonus && (
                        <span title="A client-funded bonus is set for this shop">
                          <Badge className="ml-1.5 bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300">
                            💰 {fmtMoney(bonus.amount, bonus.currency)} bonus
                          </Badge>
                        </span>
                      )}
                    </td>
                    <td className="td font-medium text-slate-800 dark:text-slate-100">
                      {p.shopper_name}
                      {p.reasons?.length > 0 && (
                        <div className="text-[11px] font-normal text-slate-400">{p.reasons.join(" · ")}</div>
                      )}
                    </td>
                    <td className="td text-right">{p.match_score}%</td>
                    <td className="td text-right">{p.distance_km != null ? `${p.distance_km} km` : "—"}</td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {proposal.unfilled.length > 0 && (
            <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-semibold">⚠ {proposal.unfilled.length} shop(s) could not be fully staffed</div>
                {proposal.unfilled.some((u: any) => u.can_expand_radius) && (
                  <button
                    className="rounded-md bg-amber-600 px-2.5 py-1 font-semibold text-white hover:bg-amber-700 disabled:opacity-50"
                    onClick={() => widenShops(proposal.unfilled, 6)}
                    disabled={optimizing}
                  >
                    {optimizing ? "Re-running…" : "Widen all & re-run"}
                  </button>
                )}
              </div>
              <p className="mt-1 text-[11px] opacity-80">
                Widen a shop's radius or add a bonus (it pays for the trip, so shoppers further away qualify) and the
                analysis re-runs with the new shoppers.
              </p>
              <ul className="mt-1.5 space-y-1.5">
                {proposal.unfilled.map((u: any, i: number) => (
                  <li key={i} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <span>
                      {u.shop_name}: {u.unfilled_slots} unfilled — {u.reason}
                      {u.far && u.nearest_outside_km != null && (
                        <span className="ml-1.5 font-semibold">
                          · nearest others are {Math.round(u.nearest_outside_km).toLocaleString()} km away (long trip)
                        </span>
                      )}
                      {u.suggested_bonus && (
                        <span className="ml-1.5 font-semibold">
                          · 🤖 {u.suggested_bonus.raises_existing ? "raise bonus to" : "suggested bonus"}{" "}
                          {fmtMoney(u.suggested_bonus.amount, u.suggested_bonus.currency)}
                          {u.suggested_bonus.fills_gap ? " (reaches enough shoppers)" : ""}
                        </span>
                      )}
                    </span>
                    <span className="flex flex-wrap gap-3 font-semibold">
                      {u.can_expand_radius && (
                        <button className="underline disabled:opacity-50" onClick={() => widenShops([u])} disabled={optimizing}>
                          Expand to {u.next_radius_km} km
                        </button>
                      )}
                      {onAddBonus && u.suggested_bonus && (
                        <button className="underline" onClick={() => onAddBonus(u.shop_id, u.suggested_bonus)}>
                          {u.suggested_bonus.raises_existing ? "Raise bonus" : "Add bonus"}
                        </button>
                      )}
                      {onOpenShop && (
                        <button className="underline" onClick={() => onOpenShop(u.shop_id)}>
                          Review shop
                        </button>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {Object.entries(blocked).map(([shopId, entry]) => (
            <div
              key={shopId}
              className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-950/40 dark:text-rose-300"
            >
              <div className="font-semibold">{entry.message}</div>
              <button
                className="mt-1.5 font-semibold underline disabled:opacity-50"
                onClick={() => enableOverSelectionAndRetry(shopId)}
                disabled={retrying === shopId}
              >
                {retrying === shopId ? "Adding…" : "Enable over-selection & add these shopper(s) anyway"}
              </button>
            </div>
          ))}
          <div className="flex justify-end gap-2">
            <button className="btn-secondary" onClick={() => setProposal(null)}>
              Review Assignments
            </button>
            <button className="btn-primary" onClick={approveAll} disabled={approving}>
              {approving ? <Spinner /> : null} {Object.keys(blocked).length ? "Retry Remaining" : "Approve All"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function MiniStat({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="card p-3 text-center">
      <div className={classNames("text-xl font-bold text-slate-900 dark:text-white", accent)}>{value}</div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
    </div>
  );
}

function CandidateCard({
  r,
  rank,
  checked,
  onToggle,
  onBreakdown,
  onViewProfile,
}: {
  r: any;
  rank: number;
  checked: boolean;
  onToggle: () => void;
  onBreakdown: () => void;
  onViewProfile: () => void;
}) {
  const meta = CLASS_META[r.classification] || CLASS_META.LOW_MATCH;
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <input
            type="checkbox"
            className="mt-1.5 h-4 w-4"
            checked={checked}
            onChange={onToggle}
            disabled={!!r.already_invited}
            title={r.already_invited ? "Already invited for this shop" : undefined}
          />
          <div className="relative">
            <Avatar name={r.name} className="h-11 w-11" />
            <span className="absolute -left-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-slate-900 text-[10px] font-bold text-white">
              {rank}
            </span>
          </div>
          <div>
            <div className="font-semibold text-slate-900 dark:text-white">{r.name}</div>
            <div className="text-xs text-slate-400">
              {AVAIL_META[(r.availability || "").toLowerCase()] || r.availability}
            </div>
            {r.recommended && (
              <span className="mt-1 inline-block rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                AI recommended
              </span>
            )}
            {r.already_invited && (
              <span className="mt-1 inline-block rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                Already invited
              </span>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-extrabold text-brand-600 dark:text-brand-400">{r.match_score}%</div>
          <Badge className={meta.badge}>{meta.label}</Badge>
          {r.confidence && (
            <div className="mt-1 text-[10px] font-semibold text-slate-400">Confidence: {r.confidence}</div>
          )}
        </div>
      </div>

      <ul className="mt-4 space-y-1 text-sm text-slate-600 dark:text-slate-400">
        {r.reasons.map((reason: string, i: number) => (
          <li key={i}>✓ {reason}</li>
        ))}
      </ul>

      <div className="mt-4 flex flex-wrap gap-2">
        <button className="btn-secondary" onClick={onBreakdown}>
          View Match Breakdown
        </button>
        <button className="btn-secondary" onClick={onViewProfile}>
          View Profile
        </button>
      </div>
    </div>
  );
}

function BreakdownModal({ r, shopId, onClose }: { r: any; shopId: string; onClose: () => void }) {
  const entries = Object.values(r.breakdown) as { label: string; points: number; max: number }[];
  const total = entries.reduce((s, e) => s + e.points, 0);
  const maxTotal = entries.reduce((s, e) => s + e.max, 0);
  const acceptance = useApi(() => api.aiAcceptanceProbability(r.shopper_id, shopId), [r.shopper_id, shopId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full max-w-md rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <h3 className="text-base font-bold text-slate-900 dark:text-white">
          {r.name} — {r.match_score}% Match
        </h3>
        {r.confidence && (
          <p className="mt-1 text-xs text-slate-400">Confidence: {r.confidence}</p>
        )}
        <div className="mt-4 space-y-2">
          {entries.map((e) => (
            <div key={e.label} className="flex items-center justify-between text-sm">
              <span className="text-slate-600 dark:text-slate-400">{e.label}</span>
              <span className="font-semibold text-slate-800 dark:text-slate-100">
                {e.points} / {e.max}
              </span>
            </div>
          ))}
          <div className="flex items-center justify-between border-t border-slate-200 pt-2 text-sm font-bold text-slate-900 dark:border-slate-700 dark:text-white">
            <span>Total</span>
            <span>
              {total} / {maxTotal}
            </span>
          </div>
        </div>
        <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-800/50 dark:text-slate-300">
          {r.reasons.join(". ")}.
        </div>

        <div className="mt-4 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">AI Acceptance Probability</div>
          {acceptance.loading && !acceptance.data ? (
            <div className="mt-1 text-sm text-slate-400">Computing…</div>
          ) : acceptance.data?.probability == null ? (
            <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{acceptance.data?.label || "Insufficient historical data"}</div>
          ) : (
            <>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-xl font-bold text-slate-900 dark:text-white">{acceptance.data.probability}%</span>
                <span className="text-[10px] font-semibold text-slate-400">{acceptance.data.label}</span>
              </div>
              {acceptance.data.factors.length > 0 && (
                <ul className="mt-1 space-y-0.5 text-xs text-slate-500 dark:text-slate-400">
                  {acceptance.data.factors.map((f: string, i: number) => (
                    <li key={i}>+ {f}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>

        <button className="btn-secondary mt-4 w-full" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}

// ------------------------------ Outreach ------------------------------ //
function OutreachTab({ campaignId, bucket }: { campaignId: string; bucket: string }) {
  const { data, loading, error, reload } = useApi(() => api.campaignOutreach(campaignId), [campaignId]);
  const navigate = useNavigate();
  if (loading && !data) return <Loading label="Loading outreach…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  const funnelStages = [
    { stage: "Sent", value: data.sent },
    { stage: "Delivered", value: data.delivered },
    { stage: "Opened", value: data.opened },
    { stage: "Clicked", value: data.clicked },
    { stage: "Accepted", value: data.accepted },
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-7">
        <KpiCard label="Invitations" value={data.invitations} accent="brand" />
        <KpiCard label="Sent" value={data.sent} accent="sky" />
        <KpiCard label="Delivered" value={data.delivered} accent="indigo" />
        <KpiCard label="Opened" value={data.opened} accent="violet" />
        <KpiCard label="Clicked" value={data.clicked} accent="amber" />
        <KpiCard label="Accepted" value={data.accepted} accent="emerald" />
        <KpiCard label="Declined" value={data.declined} accent="rose" />
      </div>
      <div className="card p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Outreach funnel</h2>
          {bucket === "completed" ? (
            <span className="text-xs font-medium text-slate-400">
              Campaign is completed — outreach is closed.
            </span>
          ) : (
            <button
              className="btn-primary"
              onClick={() => navigate(`/client/outreach?campaign=${campaignId}&type=${bucket === "upcoming" ? "upcoming" : "active"}`)}
            >
              {bucket === "upcoming" ? "Prepare Outreach" : "Create Outreach"}
            </button>
          )}
        </div>
        <Funnel stages={funnelStages} />
      </div>
    </div>
  );
}

// ------------------------------ Tracking ------------------------------ //
function TrackingTab({ campaignId }: { campaignId: string }) {
  const { data, loading, error, reload } = useApi(() => api.campaignTracking(campaignId), [campaignId]);
  const [selected, setSelected] = useState<string | null>(null);
  if (loading && !data) return <Loading label="Loading tracking…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <>
      <div className="card overflow-x-auto">
        <table className="min-w-full">
          <thead className="border-b border-slate-100 dark:border-slate-800">
            <tr>
              <th className="th">Shopper</th>
              <th className="th hidden md:table-cell">Email</th>
              <th className="th text-center">Sent</th>
              <th className="th text-center">Opened</th>
              <th className="th text-center">Clicked</th>
              <th className="th hidden xl:table-cell">Automation</th>
              <th className="th hidden lg:table-cell">Source</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
            {data.items.map((r: any) => (
              <tr
                key={r.id}
                className="cursor-pointer transition hover:bg-slate-50 dark:hover:bg-slate-800/40"
                onClick={() => setSelected(r.id)}
              >
                <td className="td font-medium text-slate-800 dark:text-slate-100">
                  {r.shopper_name}
                  <div className="text-[11px] font-normal text-slate-400">{r.reference}</div>
                </td>
                <td className="td hidden text-slate-500 md:table-cell">{r.shopper_email}</td>
                <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.sent_at} /></div></td>
                <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.opened_at} /></div></td>
                <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.clicked_at} /></div></td>
                <td className="td hidden xl:table-cell">
                  {r.automation_id ? (
                    <span className="badge bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
                      {r.automation_name} · Step {r.automation_step}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="td hidden lg:table-cell">
                  <span className="badge bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300">
                    {r.automation_id ? "Client Email / SendGrid" : "ISN Email"}
                  </span>
                </td>
              </tr>
            ))}
            {data.items.length === 0 && (
              <tr>
                <td colSpan={7} className="td py-10 text-center text-slate-400">
                  No tracked invitations yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {selected && <InvitationDrawer invitationId={selected} onClose={() => setSelected(null)} />}
    </>
  );
}

// ------------------------------ Insights ------------------------------ //
const SEVERITY: Record<string, { dot: string; ring: string }> = {
  warning: { dot: "bg-amber-500", ring: "border-amber-200 dark:border-amber-900" },
  success: { dot: "bg-emerald-500", ring: "border-emerald-200 dark:border-emerald-900" },
  info: { dot: "bg-brand-500", ring: "border-slate-200 dark:border-slate-800" },
};

function InsightsTab({ campaignId, bucket, campaignName }: { campaignId: string; bucket: string; campaignName: string }) {
  const { data, loading, error, reload } = useApi(() => api.campaignInsights(campaignId), [campaignId]);

  return (
    <div className="space-y-6">
      {bucket === "completed" ? (
        <AiPerformanceCard campaignId={campaignId} />
      ) : (
        <AiHealthCard campaignId={campaignId} bucket={bucket} />
      )}

      <RequirementParserCard campaignId={campaignId} />

      <AiFeedbackCard campaignId={campaignId} />

      <div>
        <h3 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-100">Rule-Based Insights</h3>
        {loading && !data ? (
          <Loading label="Generating insights…" />
        ) : error ? (
          <ErrorBox message={error} onRetry={reload} />
        ) : !data.insights.length ? (
          <div className="card">
            <EmptyState title="No insights yet" hint="Insights appear once outreach data is available for this campaign." />
          </div>
        ) : (
          <div className="space-y-3">
            {data.insights.map((ins: any, i: number) => {
              const sev = SEVERITY[ins.severity] || SEVERITY.info;
              return (
                <div key={i} className={"card border p-5 " + sev.ring}>
                  <div className="flex items-center gap-2">
                    <span className={"h-2.5 w-2.5 rounded-full " + sev.dot} />
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-white">{ins.title}</h3>
                  </div>
                  <p className="mt-1.5 pl-5 text-sm text-slate-600 dark:text-slate-400">{ins.message}</p>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <p className="text-xs text-slate-400">
        Insights are rule/threshold + real-data-driven — this platform does not claim a trained predictive model.
      </p>
    </div>
  );
}

function AiHealthCard({ campaignId, bucket }: { campaignId: string; bucket: string }) {
  const { data, loading, error, reload } = useApi(() => api.aiCampaignHealth(campaignId), [campaignId]);
  if (loading && !data) return <Loading label="Computing AI campaign readiness…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  const rows: [string, number][] = [
    ["Shop Coverage", data.breakdown.shop_coverage],
    ["Eligible Shoppers", data.breakdown.eligible_shoppers],
    ["Candidate Quality", data.breakdown.candidate_quality],
    ["Expected Completion", data.breakdown.expected_completion],
  ];

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          AI {bucket === "upcoming" ? "Campaign Readiness" : "Campaign Health"}
        </h3>
        <div className="text-2xl font-extrabold text-brand-600 dark:text-brand-400">{data.readiness}%</div>
      </div>
      <div className="mt-4 space-y-3">
        {rows.map(([label, val]) => (
          <div key={label}>
            <div className="mb-1 flex justify-between text-xs">
              <span className="text-slate-500 dark:text-slate-400">{label}</span>
              <span className="font-semibold text-slate-700 dark:text-slate-200">{val}%</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div className="h-full rounded-full bg-brand-500" style={{ width: `${val}%` }} />
            </div>
          </div>
        ))}
      </div>
      {data.risks.length > 0 && (
        <div className="mt-4 space-y-1.5">
          {data.risks.map((r: string, i: number) => (
            <p key={i} className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
              ⚠ {r}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function AiPerformanceCard({ campaignId }: { campaignId: string }) {
  const { data, loading, error, reload } = useApi(() => api.aiCampaignPerformance(campaignId), [campaignId]);
  if (loading && !data) return <Loading label="Computing campaign performance…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <div className="card p-5">
      <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Campaign Performance</h3>
      <div className="mt-3 grid grid-cols-3 gap-3 text-center">
        <div className="rounded-lg bg-slate-50 py-3 dark:bg-slate-800/50">
          <div className="text-xl font-bold text-slate-900 dark:text-white">{data.completion_rate}%</div>
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Completion Rate</div>
        </div>
        <div className="rounded-lg bg-slate-50 py-3 dark:bg-slate-800/50">
          <div className="text-xl font-bold text-slate-900 dark:text-white">{data.response_rate}%</div>
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Response Rate</div>
        </div>
        <div className="rounded-lg bg-slate-50 py-3 dark:bg-slate-800/50">
          <div className="text-xl font-bold text-slate-900 dark:text-white">{data.accepted}</div>
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Accepted</div>
        </div>
      </div>
      <p className="mt-4 rounded-lg bg-brand-50 px-3 py-2.5 text-sm text-brand-800 dark:bg-brand-950/40 dark:text-brand-200">
        AI Summary: {data.summary}
      </p>
    </div>
  );
}

function RequirementParserCard({ campaignId }: { campaignId: string }) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [result, setResult] = useState<any | null>(null);

  async function parse() {
    if (!text.trim()) return;
    setParsing(true);
    try {
      const res = await api.aiParseRequirements(text, campaignId);
      setResult(res);
      toast("Requirements parsed and saved to this campaign.", "success");
    } catch (e: any) {
      toast(e?.message || "Failed to parse requirements", "error");
    } finally {
      setParsing(false);
    }
  }

  return (
    <div className="card p-5">
      <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">AI Campaign Requirement Parser</h3>
      <p className="mt-1 text-xs text-slate-400">
        Describe what you need in plain language — extracted fields are saved to this campaign and used as
        additional hard filters in AI Recommendations.
      </p>
      <textarea
        className="input mt-3 h-20 resize-none text-sm"
        placeholder="e.g. Need 5 shoppers in Brooklyn for retail stores, rating above 4, within 15 km"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button className="btn-secondary mt-2" onClick={parse} disabled={parsing || !text.trim()}>
        {parsing ? <Spinner /> : null} Parse with AI
      </button>
      {result && (
        <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs dark:bg-slate-800/50">
          <pre className="whitespace-pre-wrap text-slate-600 dark:text-slate-300">
            {JSON.stringify(result.parsed_fields, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function AiFeedbackCard({ campaignId }: { campaignId: string }) {
  const { data, loading, error } = useApi(() => api.aiFeedbackAnalysis(campaignId), [campaignId]);
  if (loading && !data) return <Loading label="Analyzing shopper feedback…" />;
  if (error) return null;

  const SENT_COLOR: Record<string, string> = {
    positive: "text-emerald-600 dark:text-emerald-400",
    negative: "text-rose-600 dark:text-rose-400",
    mixed: "text-amber-600 dark:text-amber-400",
    neutral: "text-slate-500 dark:text-slate-400",
  };

  return (
    <div className="card p-5">
      <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
        AI Feedback Analysis <span className="font-normal text-slate-400">(shopper response notes)</span>
      </h3>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">{data.summary.executive_summary}</p>

      {data.summary.key_issues.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {data.summary.key_issues.map((k: any, i: number) => (
            <span key={i} className="badge bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {k.severity === "red" ? "🔴" : k.severity === "yellow" ? "🟡" : "🟢"} {k.issue} ({k.mentions})
            </span>
          ))}
        </div>
      )}

      {data.notes.length > 0 && (
        <ul className="mt-4 space-y-2 divide-y divide-slate-100 dark:divide-slate-800">
          {data.notes.map((n: any, i: number) => (
            <li key={i} className="pt-2 first:pt-0">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">{n.shopper_name}</span>
                <span className={classNames("text-[11px] font-semibold capitalize", SENT_COLOR[n.sentiment.sentiment])}>
                  {n.sentiment.sentiment}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">"{n.note}"</p>
            </li>
          ))}
        </ul>
      )}

      {data.qa_flags.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {data.qa_flags.map((f: any, i: number) => (
            <p key={i} className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
              ⚠ {f.shopper_name}: {f.reason}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

