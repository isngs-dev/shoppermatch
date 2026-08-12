import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Funnel } from "../components/Funnel";
import { InvitationDrawer } from "../components/InvitationDrawer";
import { IconSparkles } from "../components/Icons";
import { Avatar, Badge, CheckCell, EmptyState, KpiCard, Loading, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
import { classNames, fmtDate, fmtDateTime, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "shops", label: "Shops" },
  { key: "shoppers", label: "Shoppers" },
  { key: "recommendations", label: "AI Recommendations" },
  { key: "outreach", label: "Outreach" },
  { key: "tracking", label: "Tracking" },
  { key: "insights", label: "Insights" },
  { key: "audit-logs", label: "Audit Logs" },
];

export function CampaignDetail({ id }: { id: string }) {
  const [params, setParams] = useSearchParams();
  const activeTab = params.get("tab") || "overview";
  const campaign = useApi(() => api.campaign(id), [id]);

  if (campaign.loading && !campaign.data) return <Loading label="Loading campaign…" />;
  if (campaign.error) return <ErrorBox message={campaign.error} onRetry={campaign.reload} />;

  const c = campaign.data;
  const pctVal = c.total_shops ? Math.round((c.completed_shops / c.total_shops) * 100) : 0;
  const bucket = c.bucket || "active";

  return (
    <div className="space-y-6">
      <div>
        <Link
          to="/campaigns/active"
          className="text-sm font-medium text-brand-600 hover:underline dark:text-brand-400"
        >
          ← Back to Campaigns
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">{c.name}</h1>
          <Badge className={statusBadgeClass(c.status === "active" ? "accepted" : "created")}>
            {c.status}
          </Badge>
        </div>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {c.client_name} · Deadline {fmtDate(c.deadline)}
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <KpiCard label="Total Shops" value={c.total_shops} accent="brand" />
        <KpiCard label="Completed" value={c.completed_shops} accent="emerald" />
        <KpiCard label="Remaining" value={c.remaining_shops} accent="amber" />
        <KpiCard label="Progress" value={`${pctVal}%`} accent="indigo" />
        <KpiCard label="Invitations" value={c.outreach?.invitations ?? 0} accent="violet" />
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
      {activeTab === "shops" && <ShopsTab campaignId={id} />}
      {activeTab === "shoppers" && <ShoppersTab campaignId={id} />}
      {activeTab === "recommendations" && <RecommendationsTab campaignId={id} campaign={c} />}
      {activeTab === "outreach" && <OutreachTab campaignId={id} bucket={bucket} />}
      {activeTab === "tracking" && <TrackingTab campaignId={id} />}
      {activeTab === "insights" && <InsightsTab campaignId={id} />}
      {activeTab === "audit-logs" && <AuditLogsTab campaignName={c.name} />}
    </div>
  );
}

// ------------------------------ Overview ------------------------------ //
function OverviewTab({ campaign: c }: { campaign: any }) {
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="card p-5 lg:col-span-2">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          Campaign overview
        </h2>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          {c.description || "No description provided."}
        </p>
        <dl className="mt-4 grid grid-cols-2 gap-4 text-sm">
          <Field label="Client" value={c.client_name} />
          <Field label="Status" value={c.status} />
          <Field label="Created" value={fmtDate(c.created_at)} />
          <Field label="Deadline" value={fmtDate(c.deadline)} />
        </dl>
      </div>
      <div className="card p-5">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          Outreach summary
        </h2>
        <div className="mt-3 space-y-1.5 text-sm">
          <Row label="Invitations" value={c.outreach?.invitations} />
          <Row label="Sent" value={c.outreach?.sent} />
          <Row label="Delivered" value={c.outreach?.delivered} />
          <Row label="Opened" value={c.outreach?.opened} />
          <Row label="Clicked" value={c.outreach?.clicked} />
          <Row label="Accepted" value={c.outreach?.accepted} />
          <Row label="Declined" value={c.outreach?.declined} />
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

function Row({ label, value }: { label: string; value: any }) {
  return (
    <div className="flex justify-between border-b border-slate-100 py-1.5 last:border-0 dark:border-slate-800">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="font-semibold text-slate-800 dark:text-slate-100">{value ?? 0}</span>
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
            <th className="th">Response</th>
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
              <td className="td">
                {s.latest_response ? (
                  <Badge className={statusBadgeClass(s.latest_response)}>{s.latest_response}</Badge>
                ) : (
                  <span className="text-slate-300 dark:text-slate-600">—</span>
                )}
              </td>
            </tr>
          ))}
          {data.items.length === 0 && (
            <tr>
              <td colSpan={6} className="td py-10 text-center text-slate-400">
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

function RecommendationsTab({ campaignId, campaign }: { campaignId: string; campaign: any }) {
  const shops = useApi(() => api.campaignShops(campaignId), [campaignId]);
  const [shopId, setShopId] = useState("");
  const [radius, setRadius] = useState(25);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [showMore, setShowMore] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [breakdownFor, setBreakdownFor] = useState<any | null>(null);
  const [approving, setApproving] = useState(false);
  const toast = useToast();

  useEffect(() => {
    if (shops.data && !shopId) setShopId(shops.data.items[0]?.id || "");
  }, [shops.data]);

  useEffect(() => {
    // Selected shop changed — clear any previous run and selection (spec §22/23).
    setResult(null);
    setSelected(new Set());
    setShowMore(false);
  }, [shopId]);

  const selectedShop = shops.data?.items.find((s: any) => s.id === shopId);

  async function runMatching() {
    if (!shopId) return;
    setRunning(true);
    setRunError(null);
    try {
      const r = await api.aiShopRecommendations(campaignId, shopId, { limit: 20, radius });
      setResult(r);
      setSelected(new Set());
    } catch (e: any) {
      setRunError(e?.message || "AI matching failed");
    } finally {
      setRunning(false);
    }
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function approve() {
    if (!shopId || selected.size === 0) return;
    setApproving(true);
    try {
      const res = await api.approveAiRecommendations(campaignId, shopId, Array.from(selected));
      toast(`Approved ${res.count} shopper(s) — now available in Outreach (${res.created.map((c: any) => c.reference).join(", ")}).`, "success");
      setSelected(new Set());
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
  const topAndStrong = (result?.recommendations || []).filter(
    (r: any) => r.classification === "TOP_MATCH" || r.classification === "STRONG_MATCH"
  );
  const potentialAndLow = (result?.recommendations || []).filter(
    (r: any) => r.classification === "POTENTIAL_MATCH" || r.classification === "LOW_MATCH"
  );
  const visible = showMore ? [...topAndStrong, ...potentialAndLow] : topAndStrong;
  const gap = required - topAndStrong.length;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-bold text-slate-900 dark:text-white">AI Shopper Recommendations</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          AI-assisted semantic matching based on campaign requirements, experience, location and availability.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <ContextField label="Campaign" value={campaign.name} />
        <ContextField label="Shop" value={selectedShop?.shop_name || "—"} />
        <ContextField label="Required Shoppers" value={required} />
        <ContextField label="Search Radius" value={`${radius} km`} />
      </div>

      <div className="card flex flex-wrap items-end gap-3 p-4">
        <div>
          <label className="label">Shop</label>
          <select className="input h-9 w-72" value={shopId} onChange={(e) => setShopId(e.target.value)}>
            {shops.data.items.map((s: any) => (
              <option key={s.id} value={s.id}>
                {s.shop_name} — {s.city}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Search radius (km)</label>
          <input
            type="number"
            min={1}
            className="input h-9 w-28"
            value={radius}
            onChange={(e) => setRadius(Number(e.target.value) || 0)}
          />
        </div>
        <div className="ml-auto flex items-center gap-4 text-xs text-slate-400">
          <span>
            Required shoppers <span className="font-semibold text-slate-700 dark:text-slate-200">{required}</span>
          </span>
        </div>
        <button className="btn-primary" onClick={runMatching} disabled={running || !shopId}>
          {running ? <Spinner /> : <IconSparkles width={16} height={16} />}
          {running ? "Analyzing shopper profiles…" : "✨ Run AI Matching"}
        </button>
      </div>

      {runError && <ErrorBox message={runError} onRetry={runMatching} />}

      {!result && !running && (
        <div className="card">
          <EmptyState
            title="No AI matching run yet"
            hint={'Click "Run AI Matching" to analyze the shopper database against this shop’s requirements.'}
          />
        </div>
      )}

      {result && (
        <>
          <div className="card p-5">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              AI understood this requirement as
            </div>
            <p className="mt-1.5 text-sm italic text-slate-700 dark:text-slate-200">
              "{result.requirement_summary}"
            </p>
            <div className="mt-3 text-xs text-slate-400">
              Found {result.total_candidates} candidate shoppers · {result.eligible_count} eligible ·{" "}
              {result.excluded.unavailable} unavailable · {result.excluded.inactive} inactive
              {result.excluded.outside_radius ? ` · ${result.excluded.outside_radius} outside ${radius} km radius` : ""}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <MiniStat label="Analyzed" value={result.total_candidates} />
            <MiniStat label="Eligible" value={result.eligible_count} />
            <MiniStat label="Top" value={result.classification_counts.top_match} accent="text-emerald-600 dark:text-emerald-400" />
            <MiniStat label="Strong" value={result.classification_counts.strong_match} accent="text-indigo-600 dark:text-indigo-400" />
            <MiniStat label="Potential" value={result.classification_counts.potential_match} accent="text-amber-600 dark:text-amber-400" />
          </div>

          {gap > 0 && (
            <div className="card border border-amber-200 p-5 dark:border-amber-900">
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full bg-amber-500" />
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                  Recruitment Gap Detected
                </h3>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-3 text-sm">
                <div>
                  <div className="text-xs text-slate-400">Required</div>
                  <div className="font-semibold text-slate-800 dark:text-slate-100">{required}</div>
                </div>
                <div>
                  <div className="text-xs text-slate-400">Top/Strong matches</div>
                  <div className="font-semibold text-slate-800 dark:text-slate-100">{topAndStrong.length}</div>
                </div>
                <div>
                  <div className="text-xs text-slate-400">Gap</div>
                  <div className="font-semibold text-rose-600 dark:text-rose-400">{gap} shopper(s)</div>
                </div>
              </div>
              <p className="mt-3 text-sm text-slate-600 dark:text-slate-400">
                Expand recruitment radius or include potential matches to close this gap.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button className="btn-secondary" onClick={() => { setRadius((r) => r + 25); }}>
                  Expand Search Radius
                </button>
                <button className="btn-secondary" onClick={() => setShowMore(true)}>
                  Show Potential Matches
                </button>
              </div>
            </div>
          )}

          {visible.length === 0 ? (
            <div className="card">
              <EmptyState title="No candidates found" hint="Try expanding the search radius or check shopper availability." />
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
                />
              ))}
            </div>
          )}

          {!showMore && potentialAndLow.length > 0 && (
            <div className="text-center">
              <button className="btn-secondary" onClick={() => setShowMore(true)}>
                Show More Candidates ({potentialAndLow.length})
              </button>
            </div>
          )}

          {selected.size > 0 && (
            <div className="card sticky bottom-4 flex flex-wrap items-center justify-between gap-3 p-4">
              <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                Selected: {selected.size} / {required} required
                {selected.size > required && required > 0 && (
                  <span className="ml-2 text-xs font-normal text-amber-600 dark:text-amber-400">
                    You've selected more shoppers than required.
                  </span>
                )}
              </div>
              <button className="btn-primary" onClick={approve} disabled={approving}>
                {approving ? <Spinner /> : null} Approve Recommendations
              </button>
            </div>
          )}
        </>
      )}

      {breakdownFor && <BreakdownModal r={breakdownFor} onClose={() => setBreakdownFor(null)} />}
    </div>
  );
}

function ContextField({ label, value }: { label: string; value: any }) {
  return (
    <div className="card p-3">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-0.5 truncate font-semibold text-slate-800 dark:text-slate-100">{value}</div>
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
}: {
  r: any;
  rank: number;
  checked: boolean;
  onToggle: () => void;
  onBreakdown: () => void;
}) {
  const meta = CLASS_META[r.classification] || CLASS_META.LOW_MATCH;
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <input type="checkbox" className="mt-1.5 h-4 w-4" checked={checked} onChange={onToggle} />
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
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-extrabold text-brand-600 dark:text-brand-400">{r.match_score}%</div>
          <Badge className={meta.badge}>{meta.label}</Badge>
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
      </div>
    </div>
  );
}

function BreakdownModal({ r, onClose }: { r: any; onClose: () => void }) {
  const entries = Object.values(r.breakdown) as { label: string; points: number; max: number }[];
  const total = entries.reduce((s, e) => s + e.points, 0);
  const maxTotal = entries.reduce((s, e) => s + e.max, 0);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full max-w-md rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <h3 className="text-base font-bold text-slate-900 dark:text-white">
          {r.name} — {r.match_score}% Match
        </h3>
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
          <button className="btn-primary" onClick={() => navigate(`/outreach?campaign=${campaignId}`)}>
            {bucket === "upcoming" ? "Prepare Outreach" : "Create Outreach"}
          </button>
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
              <th className="th text-center">Deliv.</th>
              <th className="th text-center">Opened</th>
              <th className="th text-center">Clicked</th>
              <th className="th">Response</th>
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
                <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.delivered_at} /></div></td>
                <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.opened_at} /></div></td>
                <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.clicked_at} /></div></td>
                <td className="td">
                  <Badge className={statusBadgeClass(r.response || "pending")}>
                    {r.response ? r.response : "Pending"}
                  </Badge>
                </td>
                <td className="td hidden lg:table-cell">
                  <span className="badge bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300">
                    ISN Email
                  </span>
                </td>
              </tr>
            ))}
            {data.items.length === 0 && (
              <tr>
                <td colSpan={8} className="td py-10 text-center text-slate-400">
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

function InsightsTab({ campaignId }: { campaignId: string }) {
  const { data, loading, error, reload } = useApi(() => api.campaignInsights(campaignId), [campaignId]);
  if (loading && !data) return <Loading label="Generating insights…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data.insights.length)
    return (
      <div className="card">
        <EmptyState
          title="No insights yet"
          hint="Insights appear once outreach data is available for this campaign."
        />
      </div>
    );

  return (
    <div className="space-y-4">
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
      <p className="text-xs text-slate-400">
        Insights are rule/threshold based — the platform does not claim a trained predictive model.
      </p>
    </div>
  );
}

// ------------------------------ Audit Logs ------------------------------ //
function AuditLogsTab({ campaignName }: { campaignName: string }) {
  const { data, loading, error, reload } = useApi(() => api.auditLogs());
  if (loading && !data) return <Loading label="Loading audit logs…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  const rows = (data.items || []).filter((a: any) => a.meta?.campaign === campaignName);

  return (
    <div className="card overflow-x-auto">
      <table className="min-w-full">
        <thead className="border-b border-slate-100 dark:border-slate-800">
          <tr>
            <th className="th">Time</th>
            <th className="th">Actor</th>
            <th className="th">Action</th>
            <th className="th">Summary</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
          {rows.map((a: any) => (
            <tr key={a.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
              <td className="td whitespace-nowrap text-slate-500">{fmtDateTime(a.created_at)}</td>
              <td className="td">{a.actor}</td>
              <td className="td">
                <span className="badge bg-slate-100 font-mono text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {a.action}
                </span>
              </td>
              <td className="td">{a.summary}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={4} className="td py-10 text-center text-slate-400">
                No audit entries for this campaign yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
