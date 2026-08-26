import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Avatar, Badge, EmptyState, KpiCard, Loading, Spinner, useToast } from "../components/ui";
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

const STATE_BADGE: Record<string, string> = {
  pending: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
  active: "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  stopped: "bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300",
  completed_response: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  completed_interaction: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300",
  completed_no_response: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  completed_bounced: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  completed_failed: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
};

function cap(s: string) {
  return (s || "").split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

export function EmailAutomationPanel({ compact }: { compact?: boolean }) {
  const toast = useToast();
  const navigate = useNavigate();
  const [campaignType, setCampaignType] = useState<"active" | "upcoming">("active");
  const campaigns = useApi(() => api.campaigns({ status: campaignType }), [campaignType]);
  const [campaignId, setCampaignId] = useState("");
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

  const automations = useApi(() => (campaignId ? api.automations(campaignId) : Promise.resolve({ items: [] })), [campaignId]);

  useEffect(() => {
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
          Configure a multi-step outreach sequence for AI-recommended shoppers. Runs in the background via
          SendGrid — no browser tab needs to stay open.
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
          {campaignType === "upcoming" ? "+ Prepare Automation" : "+ New Automation"}
        </button>
      </div>

      {campaignType === "upcoming" && (
        <p className="rounded-lg bg-violet-50 px-3 py-2 text-[11px] font-medium text-violet-700 dark:bg-violet-950/40 dark:text-violet-300">
          UPCOMING CAMPAIGN — automations you create here are configured now but held as drafts. Nothing is sent
          until you set a scheduled start time (or the campaign becomes active and you press Start).
        </p>
      )}

      {automations.loading && !automations.data ? (
        <Loading label="Loading automations…" />
      ) : automations.error ? (
        <ErrorBox message={automations.error} onRetry={automations.reload} />
      ) : !automations.data?.items?.length ? (
        <div className="card">
          <EmptyState title="No automations yet" hint="Create one to start a multi-step outreach sequence for this campaign." />
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {automations.data.items.map((a: any) => (
            <button
              key={a.id}
              onClick={() => navigate(`/client/email-automation/automations/${a.id}`)}
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
                <MiniStat label="Shoppers" value={a.dashboard.total_shoppers} />
                <MiniStat label="Sent" value={a.dashboard.sent} />
                <MiniStat label="Stopped" value={a.dashboard.stopped + a.dashboard.bounced + a.dashboard.failed} />
              </div>
            </button>
          ))}
        </div>
      )}

      {showBuilder && campaignId && (
        <AutomationBuilder
          campaignId={campaignId}
          campaignType={campaignType}
          onClose={() => setShowBuilder(false)}
          onCreated={(id) => {
            setShowBuilder(false);
            navigate(`/client/email-automation/automations/${id}`);
          }}
        />
      )}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-slate-50 py-2 dark:bg-slate-800/50">
      <div className="text-base font-bold text-slate-900 dark:text-white">{value}</div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
    </div>
  );
}

// ------------------------------ Builder ------------------------------ //
function AutomationBuilder({
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
  const [waitDays, setWaitDays] = useState(2);
  // Batch emailing: off by default (everyone selected gets step 1 on
  // Start, same as before this existed). Turning it on releases shoppers
  // in waves of `batchSize`, `waitDays` apart, for up to `iterations`
  // waves — anyone beyond batchSize * iterations stays queued, never sent.
  const [batchEnabled, setBatchEnabled] = useState(false);
  const [batchSize, setBatchSize] = useState(10);
  const [iterations, setIterations] = useState(3);
  const [scheduleUpcoming, setScheduleUpcoming] = useState(campaignType === "upcoming");
  const [scheduledAt, setScheduledAt] = useState("");
  const templatesApi = useApi(() => api.emailTemplates());
  const [stepTemplates, setStepTemplates] = useState<Record<1 | 2 | 3, string>>({ 1: "", 2: "", 3: "" });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);

  const recs = useApi(
    () => (shopId ? api.aiShopRecommendations(campaignId, shopId, { limit: 20 }) : Promise.resolve(null)),
    [shopId]
  );

  useEffect(() => {
    api.campaignShops(campaignId).then((r) => {
      setShops(r.items);
      setShopId(r.items[0]?.id || "");
      setName(r.items[0] ? `${r.items[0].shop_name} — Outreach Sequence` : "");
    });
  }, [campaignId]);

  useEffect(() => {
    const shop = shops.find((s) => s.id === shopId);
    if (shop) setName(`${shop.shop_name} — Outreach Sequence`);
    setSelected(new Set());
  }, [shopId]);

  // Default to everyone the AI recommended selected — most of the time
  // that's exactly who should get the automation, and it's faster to
  // deselect the few exceptions than to hand-pick from a list of 20.
  useEffect(() => {
    if (recs.data?.recommendations) {
      setSelected(new Set(recs.data.recommendations.map((r: any) => r.shopper_id)));
    }
  }, [recs.data]);

  const templatesByName = useMemo(() => {
    const map: Record<string, any> = {};
    for (const t of templatesApi.data?.items || []) map[t.name] = t;
    return map;
  }, [templatesApi.data]);

  const candidates = recs.data?.recommendations || [];

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function create() {
    if (!shopId || !name.trim() || selected.size === 0) {
      toast("Pick a shop, name the automation, and select at least one shopper.", "error");
      return;
    }
    setCreating(true);
    try {
      const automation = await api.createAutomation({
        campaign_id: campaignId,
        shop_id: shopId,
        name: name.trim(),
        step1_template_id: stepTemplates[1] || null,
        step2_template_id: stepTemplates[2] || null,
        step3_template_id: stepTemplates[3] || null,
        wait_days: waitDays,
        scheduled_start_at: scheduleUpcoming && scheduledAt ? new Date(scheduledAt).toISOString() : null,
        batch_size: batchEnabled ? batchSize : null,
        total_iterations: batchEnabled ? iterations : 1,
      });
      await api.addAutomationShoppers(automation.id, Array.from(selected));
      toast(`Automation "${name.trim()}" created with ${selected.size} shopper(s). Review and Start it.`, "success");
      onCreated(automation.id);
    } catch (e: any) {
      toast(e?.message || "Failed to create automation", "error");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <h3 className="text-base font-bold text-slate-900 dark:text-white">New Email Automation</h3>

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
            <label className="label">Wait between steps (days)</label>
            <input type="number" min={1} max={14} className="input" value={waitDays} onChange={(e) => setWaitDays(Number(e.target.value) || 2)} />
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

        <div className="mt-4 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <label className="label flex items-center gap-2">
            <input type="checkbox" checked={batchEnabled} onChange={(e) => setBatchEnabled(e.target.checked)} />
            Batch emailing
          </label>
          <p className="mt-1 text-[11px] text-slate-400">
            Off sends step 1 to every selected shopper immediately on Start. On releases them in waves instead —
            {" "}{batchSize} shopper(s) every {waitDays} day(s), for {iterations} iteration(s) (
            {batchSize * iterations} shopper(s) total reached; anyone beyond that stays queued, unsent).
          </p>
          {batchEnabled && (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <div>
                <label className="label">Batch size (shoppers per wave)</label>
                <input
                  type="number"
                  min={1}
                  max={1000}
                  className="input"
                  value={batchSize}
                  onChange={(e) => setBatchSize(Math.max(1, Number(e.target.value) || 1))}
                />
              </div>
              <div>
                <label className="label">Iterations (number of waves)</label>
                <input
                  type="number"
                  min={1}
                  max={52}
                  className="input"
                  value={iterations}
                  onChange={(e) => setIterations(Math.max(1, Number(e.target.value) || 1))}
                />
              </div>
            </div>
          )}
        </div>

        <div className="mt-4">
          <div className="label">Email steps</div>
          <div className="grid gap-2 sm:grid-cols-3">
            {([1, 2, 3] as const).map((step) => {
              const defaultName = step === 1 ? "Initial Invitation" : step === 2 ? "Reminder" : "Final Reminder";
              return (
                <div key={step} className="rounded-lg border border-slate-200 p-2.5 dark:border-slate-700">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Step {step}</div>
                  <select
                    className="input mt-1 h-9 text-xs"
                    value={stepTemplates[step]}
                    onChange={(e) => setStepTemplates((prev) => ({ ...prev, [step]: e.target.value }))}
                  >
                    <option value="">{defaultName} (default)</option>
                    {(templatesApi.data?.items || []).map((t: any) => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                </div>
              );
            })}
          </div>
          <p className="mt-1 text-[11px] text-slate-400">
            Max 3 emails per shopper. Any shopper who clicks, visits the assignment page, accepts, or declines
            stops immediately — never reaches step 2 or 3.
          </p>
        </div>

        <div className="mt-4">
          <div className="flex items-center justify-between">
            <div className="label !mb-0">AI-recommended shoppers for this shop</div>
            {!!candidates.length && (
              <div className="flex gap-2 text-[11px]">
                <button
                  type="button"
                  className="font-semibold text-brand-600 hover:underline dark:text-brand-400"
                  onClick={() => setSelected(new Set(candidates.map((r: any) => r.shopper_id)))}
                >
                  Select all
                </button>
                <button
                  type="button"
                  className="font-semibold text-slate-400 hover:underline"
                  onClick={() => setSelected(new Set())}
                >
                  Clear
                </button>
              </div>
            )}
          </div>
          {shopId && recs.loading && !recs.data ? (
            <div className="mt-1.5 flex items-center gap-2 text-sm text-slate-400"><Spinner /> AI is matching shoppers…</div>
          ) : !candidates.length ? (
            <p className="mt-1.5 text-sm text-slate-400">No candidates found. Try a different shop.</p>
          ) : (
            <div className="mt-1.5 max-h-64 space-y-1.5 overflow-y-auto rounded-lg border border-slate-100 p-2 dark:border-slate-800">
              {candidates.map((r: any) => (
                <label
                  key={r.shopper_id}
                  className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800/50"
                >
                  <input type="checkbox" checked={selected.has(r.shopper_id)} onChange={() => toggle(r.shopper_id)} />
                  <Avatar name={r.name} className="h-7 w-7" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">{r.name}</div>
                    <div className="text-[11px] text-slate-400">{r.city} · {r.match_score}% match</div>
                  </div>
                </label>
              ))}
            </div>
          )}
          <div className="mt-1 text-[11px] text-slate-400">Selected: {selected.size}</div>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={create} disabled={creating}>
            {creating ? <Spinner /> : null} Create Automation
          </button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------ Detail / Dashboard ------------------------------ //
// Its own routed page (/client/email-automation/automations/:id) rather than a modal
// over the Email Automation list — each automation gets a real URL you can
// bookmark/share/refresh, and Back is genuine browser back navigation.
export function AutomationDetailPage() {
  const { automationId } = useParams<{ automationId: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const { data, loading, error, reload } = useApi(() => api.automation(automationId!), [automationId]);
  const [busy, setBusy] = useState<string | null>(null);
  const [previewFor, setPreviewFor] = useState<{ shopperId: string; step: number } | null>(null);

  useEffect(() => {
    const id = window.setInterval(reload, 6000);
    return () => window.clearInterval(id);
  }, [reload]);

  async function act(action: "start" | "pause" | "resume" | "stop") {
    setBusy(action);
    try {
      const fn = { start: api.startAutomation, pause: api.pauseAutomation, resume: api.resumeAutomation, stop: api.stopAutomation }[action];
      await fn(automationId!);
      toast(`Automation ${action === "start" ? "started" : action + "d"}.`, "success");
      reload();
    } catch (e: any) {
      toast(e?.message || `Failed to ${action} automation`, "error");
    } finally {
      setBusy(null);
    }
  }

  const backLink = (
    <button
      className="text-sm font-semibold text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100"
      onClick={() => navigate("/client/email-automation")}
    >
      ← Back to Email Automation
    </button>
  );

  if (loading && !data) {
    return (
      <div className="space-y-4">
        {backLink}
        <Loading label="Loading automation…" />
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="space-y-4">
        {backLink}
        <ErrorBox message={error || "Automation not found"} onRetry={reload} />
      </div>
    );
  }

  const d = data.dashboard;

  return (
    <div className="space-y-4">
      {backLink}

      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900 dark:text-white">{data.name}</h1>
            <Badge className={STATUS_BADGE[data.status] || STATUS_BADGE.draft}>{cap(data.status)}</Badge>
          </div>
          <p className="mt-1 text-sm text-slate-400">
            {data.campaign_name} · {data.shop_name} · every {data.wait_days} day(s) · up to {data.max_steps} emails/shopper
            {data.batch_size ? ` · batch of ${data.batch_size}, ${data.total_iterations} iteration(s)` : ""}
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
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 sm:grid-cols-5">
        <KpiCard label="Total Shoppers" value={d.total_shoppers} accent="brand" />
        <KpiCard label="Sent" value={d.sent} accent="sky" />
        <KpiCard label="Interacted" value={d.interacted} accent="indigo" />
        <KpiCard label="Accepted/Declined" value={d.accepted_or_declined} accent="emerald" />
        <KpiCard label="No Response" value={d.no_response} accent="amber" />
        <KpiCard label="Bounced" value={d.bounced} accent="rose" />
        <KpiCard label="Failed" value={d.failed} accent="rose" />
        <KpiCard label="Stopped" value={d.stopped} accent="slate" />
        <KpiCard label="Pending" value={d.pending} accent="slate" />
      </div>

      <div className="card overflow-x-auto !p-0">
        <table className="min-w-full text-sm">
          <thead className="border-b border-slate-100 dark:border-slate-800">
            <tr>
              <th className="th">Shopper</th>
              <th className="th text-center">Step</th>
              <th className="th">Status</th>
              <th className="th">Last Event</th>
              <th className="th hidden lg:table-cell">Last Sent</th>
              <th className="th hidden lg:table-cell">Next Action</th>
              <th className="th">Preview</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
            {data.shoppers.map((s: any) => (
              <tr key={s.id}>
                <td className="td font-medium text-slate-800 dark:text-slate-100">
                  {s.shopper_name}
                  <div className="text-[11px] font-normal text-slate-400">{s.shopper_email}</div>
                </td>
                <td className="td text-center">{s.current_step} / {data.max_steps}</td>
                <td className="td">
                  <Badge className={STATE_BADGE[s.status] || STATE_BADGE.pending}>{cap(s.status)}</Badge>
                </td>
                <td className="td text-slate-500">{s.last_event ? cap(s.last_event) : "—"}</td>
                <td className="td hidden text-slate-500 lg:table-cell">{s.last_email_sent_at ? fmtDateTime(s.last_email_sent_at) : "—"}</td>
                <td className="td hidden text-slate-500 lg:table-cell">{s.next_action_at ? fmtDateTime(s.next_action_at) : "—"}</td>
                <td className="td">
                  <select
                    className="input h-8 w-28 text-xs"
                    value=""
                    onChange={(e) => {
                      if (e.target.value) setPreviewFor({ shopperId: s.shopper_id, step: Number(e.target.value) });
                      e.target.value = "";
                    }}
                  >
                    <option value="">View…</option>
                    {[1, 2, 3].map((st) => (
                      <option key={st} value={st}>Step {st}</option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
            {data.shoppers.length === 0 && (
              <tr>
                <td colSpan={7} className="td py-8 text-center text-slate-400">No shoppers in this automation.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {previewFor && (
        <EmailPreviewModal
          automationId={automationId!}
          shopperId={previewFor.shopperId}
          step={previewFor.step}
          onClose={() => setPreviewFor(null)}
        />
      )}
    </div>
  );
}

function EmailPreviewModal({ automationId, shopperId, step, onClose }: { automationId: string; shopperId: string; step: number; onClose: () => void }) {
  const { data, loading, error } = useApi(() => api.automationPreview(automationId, shopperId, step), [automationId, shopperId, step]);
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
            <iframe title="Email step preview" srcDoc={data.html} className="h-[420px] w-full border-0 bg-white" />
          </>
        )}
        <div className="border-t border-slate-200 p-3 text-right dark:border-slate-800">
          <button className="btn-secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
