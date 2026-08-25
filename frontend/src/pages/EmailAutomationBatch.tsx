import { useEffect, useState } from "react";
import { Badge, EmptyState, KpiCard, Loading, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
import { classNames, fmtDateTime } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  scheduled: "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300",
  active: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  paused: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  stopped: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  completed: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300",
};

function cap(s: string) {
  return (s || "").split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

// --------------------------------------------------------------------------- //
// Batch (wave) automation — deliberately a separate module from the 3-step
// reminder Sequences panel. This one expands reach over time: every
// `wait_days`, the NEXT `batch_size` shoppers from an AI-ranked pool get the
// template email, for `total_iterations` waves — never the same shopper
// twice. Active/Upcoming campaign selection lives here now, not on the
// Send Invitation compose page.
// --------------------------------------------------------------------------- //
export function EmailAutomationBatchPanel({ compact }: { compact?: boolean }) {
  const [campaignType, setCampaignType] = useState<"active" | "upcoming">("active");
  const campaigns = useApi(() => api.campaigns({ status: campaignType }), [campaignType]);
  const [campaignId, setCampaignId] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showBuilder, setShowBuilder] = useState(false);

  useEffect(() => {
    if (!campaigns.data) return;
    const items = campaigns.data.items;
    if (!items.length) {
      setCampaignId("");
      return;
    }
    if (items.some((c: any) => c.id === campaignId)) return;
    setCampaignId(items[0].id);
  }, [campaigns.data]);

  const automations = useApi(
    () => (campaignId ? api.batchAutomations(campaignId) : Promise.resolve({ items: [] })),
    [campaignId]
  );

  useEffect(() => {
    setSelectedId(null);
    setShowBuilder(false);
  }, [campaignId]);

  useEffect(() => {
    const id = window.setInterval(() => automations.reload(), 8000);
    return () => window.clearInterval(id);
  }, [automations.reload]);

  return (
    <div className="space-y-6">
      {!compact && (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Expand recruitment reach over time: every few days, email the next batch of AI-ranked shoppers — never the
          same person twice. Runs in the background, no browser tab needs to stay open.
        </p>
      )}

      <div className="card flex flex-wrap items-end gap-3 p-4">
        <div className="inline-flex rounded-xl bg-slate-100 p-1 dark:bg-slate-800/70">
          {(["active", "upcoming"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setCampaignType(t)}
              className={classNames(
                "rounded-lg px-3.5 py-1.5 text-xs font-semibold transition",
                campaignType === t ? "bg-brand-600 text-white shadow" : "text-slate-500 hover:text-slate-800 dark:text-slate-400"
              )}
            >
              {t === "active" ? "Active Campaigns" : "Upcoming Campaigns"}
            </button>
          ))}
        </div>
        <div>
          <label className="label">Campaign</label>
          {!campaigns.data?.items.length ? (
            <div className="input flex h-9 items-center text-sm text-slate-400">No {campaignType} campaigns</div>
          ) : (
            <select className="input h-9 w-72" value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
              {campaigns.data.items.map((c: any) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          )}
        </div>
        <button className="btn-primary ml-auto" onClick={() => setShowBuilder(true)} disabled={!campaignId}>
          {campaignType === "upcoming" ? "+ Prepare Batch Automation" : "+ New Batch Automation"}
        </button>
      </div>

      {campaignType === "upcoming" && (
        <p className="rounded-lg bg-violet-50 px-3 py-2 text-[11px] font-medium text-violet-700 dark:bg-violet-950/40 dark:text-violet-300">
          UPCOMING CAMPAIGN — batch automations you create here are configured now but held as drafts. Nothing is
          sent until you set a scheduled start time (or the campaign becomes active and you press Start).
        </p>
      )}

      {automations.loading && !automations.data ? (
        <Loading label="Loading batch automations…" />
      ) : automations.error ? (
        <ErrorBox message={automations.error} onRetry={automations.reload} />
      ) : !automations.data?.items?.length ? (
        <div className="card">
          <EmptyState title="No batch automations yet" hint="Create one to start a wave-based recruitment drip for this campaign." />
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {automations.data.items.map((a: any) => (
            <button
              key={a.id}
              onClick={() => setSelectedId(a.id)}
              className="card p-4 text-left transition hover:border-brand-300 dark:hover:border-brand-700"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-semibold text-slate-900 dark:text-white">{a.name}</div>
                  <div className="truncate text-xs text-slate-400">{a.shop_name}</div>
                </div>
                <Badge className={STATUS_BADGE[a.status] || STATUS_BADGE.draft}>{cap(a.status)}</Badge>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                <MiniStat label="Wave" value={`${a.current_iteration}/${a.total_iterations}`} />
                <MiniStat label="Sent" value={a.sent_count} />
                <MiniStat label="Remaining" value={a.remaining_count} />
              </div>
              <div className="mt-2 text-[11px] text-slate-400">
                Batch of {a.batch_size} every {a.wait_days} day(s)
                {a.next_run_at && <> · next wave {fmtDateTime(a.next_run_at)}</>}
              </div>
            </button>
          ))}
        </div>
      )}

      {showBuilder && campaignId && (
        <BatchAutomationBuilder
          campaignId={campaignId}
          campaignType={campaignType}
          onClose={() => setShowBuilder(false)}
          onCreated={(id) => {
            setShowBuilder(false);
            automations.reload();
            setSelectedId(id);
          }}
        />
      )}

      {selectedId && (
        <BatchAutomationDetail automationId={selectedId} onClose={() => setSelectedId(null)} onChanged={automations.reload} />
      )}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg bg-slate-50 py-2 dark:bg-slate-800/50">
      <div className="text-base font-bold text-slate-900 dark:text-white">{value}</div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
    </div>
  );
}

// ------------------------------ Builder ------------------------------ //
function BatchAutomationBuilder({
  campaignId,
  campaignType,
  onClose,
  onCreated,
}: {
  campaignId: string;
  campaignType: "active" | "upcoming";
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const toast = useToast();
  const [shops, setShops] = useState<any[]>([]);
  const [shopId, setShopId] = useState("");
  const [name, setName] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [batchSize, setBatchSize] = useState(10);
  const [waitDays, setWaitDays] = useState(2);
  const [totalIterations, setTotalIterations] = useState(3);
  const [scheduleUpcoming, setScheduleUpcoming] = useState(campaignType === "upcoming");
  const [scheduledAt, setScheduledAt] = useState("");
  const templatesApi = useApi(() => api.emailTemplates());
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api.campaignShops(campaignId).then((r) => {
      setShops(r.items);
      setShopId(r.items[0]?.id || "");
      setName(r.items[0] ? `${r.items[0].shop_name} — Batch Automation` : "");
    });
  }, [campaignId]);

  useEffect(() => {
    const shop = shops.find((s) => s.id === shopId);
    if (shop) setName(`${shop.shop_name} — Batch Automation`);
  }, [shopId]);

  async function create() {
    if (!shopId || !name.trim()) {
      toast("Pick a shop and name the automation.", "error");
      return;
    }
    setCreating(true);
    try {
      const automation = await api.createBatchAutomation({
        campaign_id: campaignId,
        shop_id: shopId,
        name: name.trim(),
        template_id: templateId || null,
        batch_size: batchSize,
        wait_days: waitDays,
        total_iterations: totalIterations,
        scheduled_start_at: scheduleUpcoming && scheduledAt ? new Date(scheduledAt).toISOString() : null,
      });
      toast(
        `Batch automation "${name.trim()}" created — ${automation.candidate_count} candidate shopper(s) ranked and ready. Review and Start it.`,
        "success"
      );
      onCreated(automation.id);
    } catch (e: any) {
      toast(e?.message || "Failed to create batch automation", "error");
    } finally {
      setCreating(false);
    }
  }

  const totalReach = batchSize * totalIterations;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <h3 className="text-base font-bold text-slate-900 dark:text-white">New Batch Automation</h3>
        <p className="mt-1 text-xs text-slate-400">
          Emails the next batch of AI-ranked shoppers every wait period, expanding reach wave by wave — never the same
          shopper twice.
        </p>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Shop</label>
            <select className="input" value={shopId} onChange={(e) => setShopId(e.target.value)}>
              {shops.map((s) => (
                <option key={s.id} value={s.id}>{s.shop_name} — {s.city}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Automation name</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="label">Email template</label>
            <select className="input" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
              <option value="">Default invitation template</option>
              {(templatesApi.data?.items || []).map((t: any) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label flex items-center gap-2">
              <input type="checkbox" checked={scheduleUpcoming} onChange={(e) => setScheduleUpcoming(e.target.checked)} />
              Schedule start (don't send yet)
            </label>
            <input
              type="datetime-local"
              className="input"
              disabled={!scheduleUpcoming}
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
            />
          </div>
        </div>

        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <div>
            <label className="label">Batch size</label>
            <input type="number" min={1} max={200} className="input" value={batchSize} onChange={(e) => setBatchSize(Number(e.target.value) || 1)} />
            <p className="mt-1 text-[11px] text-slate-400">Shoppers emailed per wave</p>
          </div>
          <div>
            <label className="label">Wait between waves (days)</label>
            <input type="number" min={1} max={30} className="input" value={waitDays} onChange={(e) => setWaitDays(Number(e.target.value) || 1)} />
            <p className="mt-1 text-[11px] text-slate-400">e.g. 2 = next wave 2 days later</p>
          </div>
          <div>
            <label className="label">Iterations (waves)</label>
            <input type="number" min={1} max={20} className="input" value={totalIterations} onChange={(e) => setTotalIterations(Number(e.target.value) || 1)} />
            <p className="mt-1 text-[11px] text-slate-400">How many waves total</p>
          </div>
        </div>

        <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-800/50 dark:text-slate-300">
          Up to <span className="font-semibold">{totalReach}</span> shopper(s) total across {totalIterations} wave(s),{" "}
          {batchSize} at a time, {waitDays} day(s) apart — automatically capped to however many eligible shoppers
          actually exist for this shop.
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={create} disabled={creating}>
            {creating ? <Spinner /> : null} Create Batch Automation
          </button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------ Detail ------------------------------ //
function BatchAutomationDetail({ automationId, onClose, onChanged }: { automationId: string; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const { data, loading, error, reload } = useApi(() => api.batchAutomation(automationId), [automationId]);
  const [busy, setBusy] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    const id = window.setInterval(reload, 6000);
    return () => window.clearInterval(id);
  }, [reload]);

  async function act(action: "start" | "pause" | "resume" | "stop") {
    setBusy(action);
    try {
      const fn = {
        start: api.startBatchAutomation,
        pause: api.pauseBatchAutomation,
        resume: api.resumeBatchAutomation,
        stop: api.stopBatchAutomation,
      }[action];
      await fn(automationId);
      toast(`Batch automation ${action === "start" ? "started" : action + "d"}.`, "success");
      reload();
      onChanged();
    } catch (e: any) {
      toast(e?.message || `Failed to ${action} batch automation`, "error");
    } finally {
      setBusy(null);
    }
  }

  if (loading && !data) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="absolute inset-0 bg-black/50" onClick={onClose} />
        <div className="relative rounded-xl bg-white p-8 dark:bg-slate-900"><Spinner /></div>
      </div>
    );
  }
  if (error || !data) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-slate-900 dark:text-white">{data.name}</h3>
              <Badge className={STATUS_BADGE[data.status] || STATUS_BADGE.draft}>{cap(data.status)}</Badge>
            </div>
            <p className="text-xs text-slate-400">
              {data.campaign_name} · {data.shop_name} · batch of {data.batch_size} every {data.wait_days} day(s) ·{" "}
              {data.total_iterations} wave(s) · {data.template_name || "Default invitation template"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {(data.status === "draft" || data.status === "paused" || data.status === "stopped") && (
              <button className="btn-primary h-9" onClick={() => act("start")} disabled={!!busy}>
                {busy === "start" ? <Spinner /> : null} {data.status === "paused" ? "Resume via Start" : "Start"}
              </button>
            )}
            {(data.status === "active" || data.status === "scheduled") && (
              <button className="btn-secondary h-9" onClick={() => act("pause")} disabled={!!busy}>
                {busy === "pause" ? <Spinner /> : null} Pause
              </button>
            )}
            {data.status === "paused" && (
              <button className="btn-primary h-9" onClick={() => act("resume")} disabled={!!busy}>
                {busy === "resume" ? <Spinner /> : null} Resume
              </button>
            )}
            {["active", "scheduled", "paused"].includes(data.status) && (
              <button className="btn-secondary h-9 text-rose-600" onClick={() => act("stop")} disabled={!!busy}>
                {busy === "stop" ? <Spinner /> : null} Stop
              </button>
            )}
            <button className="btn-secondary h-9" onClick={() => setShowPreview(true)}>Preview Email</button>
            <button className="btn-ghost h-9" onClick={onClose}>Close</button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-3 sm:grid-cols-5">
          <KpiCard label="Wave" value={`${data.current_iteration}/${data.total_iterations}`} accent="brand" />
          <KpiCard label="Candidates" value={data.candidate_count} accent="slate" />
          <KpiCard label="Sent" value={data.sent_count} accent="sky" />
          <KpiCard label="Remaining" value={data.remaining_count} accent="amber" />
        </div>

        <div className="mt-4 rounded-lg border border-slate-100 p-3 text-sm dark:border-slate-800">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <Row label="Next wave" value={data.next_run_at ? fmtDateTime(data.next_run_at) : "—"} />
            <Row label="Scheduled start" value={data.scheduled_start_at ? fmtDateTime(data.scheduled_start_at) : "Immediate"} />
            <Row label="Started" value={data.started_at ? fmtDateTime(data.started_at) : "Not yet"} />
            <Row label="Completed" value={data.completed_at ? fmtDateTime(data.completed_at) : "—"} />
            <Row label="Created by" value={data.created_by} />
            <Row label="Created" value={fmtDateTime(data.created_at)} />
          </div>
        </div>

        <p className="mt-3 text-[11px] text-slate-400">
          Each wave emails the next {data.batch_size} shopper(s) from the ranked candidate pool and never repeats one
          already sent. The automation completes once all {data.total_iterations} wave(s) have run or the candidate
          pool is exhausted.
        </p>
      </div>

      {showPreview && <BatchPreviewModal automationId={automationId} onClose={() => setShowPreview(false)} />}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-slate-700 dark:text-slate-200">{value}</div>
    </div>
  );
}

function BatchPreviewModal({ automationId, onClose }: { automationId: string; onClose: () => void }) {
  const { data, loading, error } = useApi(() => api.batchAutomationPreview(automationId), [automationId]);
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-lg overflow-hidden rounded-xl bg-white shadow-2xl dark:bg-slate-900">
        {loading && !data ? (
          <div className="p-8"><Spinner /></div>
        ) : error ? (
          <div className="p-6 text-sm text-rose-500">{error}</div>
        ) : (
          <>
            <div className="border-b border-slate-200 p-4 dark:border-slate-800">
              <div className="text-xs text-slate-400">To: {data.to}</div>
              <div className="text-sm font-semibold text-slate-900 dark:text-white">{data.subject}</div>
            </div>
            <iframe
              title="Batch wave email preview"
              srcDoc={data.html + "<style>a{pointer-events:none!important;cursor:default!important;}</style>"}
              sandbox=""
              className="h-[420px] w-full border-0 bg-white"
            />
          </>
        )}
        <div className="border-t border-slate-200 p-3 text-right dark:border-slate-800">
          <button className="btn-secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
