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

const VOICE_CALL_BADGE: Record<string, string> = {
  interested: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  not_interested: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  undecided: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  voicemail: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  calling: "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  queued: "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  no_answer: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
  failed: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  completed: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300",
  default: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
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
                  <div className="truncate text-xs text-slate-400">{a.shop_name || "All shops in campaign"}</div>
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

      {showBuilder && (
        <AutomationBuilder
          initialCampaignId={campaignId}
          initialCampaignType={campaignType}
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
  initialCampaignId,
  initialCampaignType,
  onClose,
  onCreated,
}: {
  initialCampaignId: string;
  initialCampaignType: "active" | "upcoming";
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const toast = useToast();
  // Always campaign-wide — there is no "pick one shop" mode. Active/Upcoming
  // + Campaign are chosen right here (seeded from whatever was selected on
  // the page behind this modal), so the whole flow is self-contained.
  // "Entire Campaign" drops the active/upcoming filter entirely — it lists
  // every campaign (excluding completed/cancelled) in one flat dropdown so
  // the client doesn't need to know or care which bucket theirs is in.
  const [campaignType, setCampaignType] = useState<"active" | "upcoming" | "all">(initialCampaignType);
  const campaignsApi = useApi(
    () => api.campaigns(campaignType === "all" ? {} : { status: campaignType }),
    [campaignType]
  );
  const eligibleCampaigns = useMemo(
    () =>
      campaignType === "all"
        ? (campaignsApi.data?.items || []).filter((c: any) => c.bucket === "active" || c.bucket === "upcoming")
        : campaignsApi.data?.items || [],
    [campaignsApi.data, campaignType]
  );
  const [campaignId, setCampaignId] = useState(initialCampaignId);

  useEffect(() => {
    if (!campaignsApi.data) return;
    if (!eligibleCampaigns.length) {
      setCampaignId("");
      return;
    }
    if (eligibleCampaigns.some((c: any) => c.id === campaignId)) return;
    setCampaignId(eligibleCampaigns[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignsApi.data, campaignType]);

  const selectedCampaign = eligibleCampaigns.find((c: any) => c.id === campaignId);
  const campaignName = selectedCampaign?.name || "";

  const [name, setName] = useState("");
  // Kept as raw text while typing (not a number) so backspacing to clear
  // the field doesn't immediately snap back to a fallback value — only
  // clamped to a real number where it's actually used, below.
  const [waitDaysInput, setWaitDaysInput] = useState("2");
  const waitDays = Math.max(1, parseInt(waitDaysInput, 10) || 2);
  // Batch emailing: off by default (everyone selected gets step 1 on
  // Start, same as before this existed). Turning it on releases shoppers
  // in waves of `batchSize`, `waitDays` apart, for up to `iterations`
  // waves — anyone beyond batchSize * iterations stays queued, never sent.
  const [batchEnabled, setBatchEnabled] = useState(false);
  const [batchSizeInput, setBatchSizeInput] = useState("10");
  const [iterationsInput, setIterationsInput] = useState("3");
  const batchSize = Math.max(1, parseInt(batchSizeInput, 10) || 1);
  const iterations = Math.max(1, parseInt(iterationsInput, 10) || 1);
  const [scheduleUpcoming, setScheduleUpcoming] = useState(initialCampaignType === "upcoming");
  const [scheduledAt, setScheduledAt] = useState("");
  // AI Voice Call Follow-Up (step 07) — off by default; the email sequence
  // behaves identically either way. Only fires once a shopper exhausts
  // every email step with no reply — see services/voice_call_scheduler.py.
  const [voiceCallEnabled, setVoiceCallEnabled] = useState(false);
  const [voiceCallDelayInput, setVoiceCallDelayInput] = useState("2");
  const [voiceCallRetryGapInput, setVoiceCallRetryGapInput] = useState("3");
  const [voiceCallMaxAttemptsInput, setVoiceCallMaxAttemptsInput] = useState("2");
  const voiceCallDelayDays = Math.max(0, parseInt(voiceCallDelayInput, 10) || 0);
  const voiceCallRetryGapDays = Math.max(1, parseInt(voiceCallRetryGapInput, 10) || 1);
  const voiceCallMaxAttempts = Math.max(1, parseInt(voiceCallMaxAttemptsInput, 10) || 1);
  const templatesApi = useApi(() => api.emailTemplates());
  // Batch emailing ties step count to wave count: each wave gets its own
  // distinct email instead of everyone sharing the same fixed 3-step
  // Initial Invitation/Reminder/Final Reminder trio. Off (or off-batch)
  // always stays at the original 3 steps.
  const stepCount = batchEnabled ? Math.max(1, iterations) : 3;
  const [stepTemplates, setStepTemplates] = useState<Record<number, string>>({ 1: "", 2: "", 3: "" });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    setStepTemplates((prev) => {
      const next = { ...prev };
      for (let i = 1; i <= stepCount; i++) if (!(i in next)) next[i] = "";
      return next;
    });
  }, [stepCount]);

  // The same AI Assignment Optimizer "Auto Assign Shoppers" already uses —
  // one pass across every shop in the campaign, never proposing the same
  // shopper for two shops, respecting each shop's own required_shoppers
  // count. Shops never surface in this UI; they're only used internally to
  // route each shopper's actual invitation correctly.
  const campaignRecs = useApi(
    () => (campaignId ? api.aiOptimizeAssignments(campaignId) : Promise.resolve(null)),
    [campaignId]
  );

  useEffect(() => {
    setScheduleUpcoming(campaignType === "all" ? selectedCampaign?.bucket === "upcoming" : campaignType === "upcoming");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignType, campaignId]);

  useEffect(() => {
    setName(campaignName ? `${campaignName} — Campaign Sequence` : "Campaign Sequence");
    setSelected(new Set());
  }, [campaignId, campaignName]);

  // Default to everyone the AI proposed selected — most of the time that's
  // exactly who should get the automation ("sabko mail jaana chahiye"), and
  // it's faster to deselect a few exceptions than to hand-pick from a list.
  useEffect(() => {
    if (campaignRecs.data?.proposals) {
      setSelected(new Set(campaignRecs.data.proposals.map((p: any) => p.shopper_id)));
    }
  }, [campaignRecs.data]);

  const candidates = useMemo(
    () =>
      (campaignRecs.data?.proposals || []).map((p: any) => ({
        shopper_id: p.shopper_id,
        name: p.shopper_name,
        match_score: p.match_score,
        shop_id: p.shop_id,
        shop_name: p.shop_name,
      })),
    [campaignRecs.data]
  );

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function create() {
    if (!campaignId) {
      toast("Pick a campaign first.", "error");
      return;
    }
    if (!name.trim() || selected.size === 0) {
      toast("Name the automation and select at least one shopper.", "error");
      return;
    }
    setCreating(true);
    try {
      // One automation for the whole campaign — shop is never a concept the
      // client sees or picks. Each selected shopper still needs a real shop
      // behind the scenes (an Invitation always belongs to one), so it's
      // sent alongside shopper_ids, positionally, from the AI proposal.
      const chosen = candidates.filter((c: any) => selected.has(c.shopper_id));
      const automation = await api.createAutomation({
        campaign_id: campaignId,
        shop_id: null,
        name: name.trim(),
        step_template_ids: Array.from({ length: stepCount }, (_, i) => stepTemplates[i + 1] || null),
        wait_days: waitDays,
        scheduled_start_at: scheduleUpcoming && scheduledAt ? new Date(scheduledAt).toISOString() : null,
        batch_size: batchEnabled ? batchSize : null,
        total_iterations: batchEnabled ? iterations : 1,
        voice_call_enabled: voiceCallEnabled,
        voice_call_delay_days: voiceCallDelayDays,
        voice_call_retry_gap_days: voiceCallRetryGapDays,
        voice_call_max_attempts: voiceCallMaxAttempts,
      });
      await api.addAutomationShoppers(
        automation.id,
        chosen.map((c: any) => c.shopper_id),
        chosen.map((c: any) => c.shop_id)
      );
      toast(`Automation "${name.trim()}" created with ${chosen.length} shopper(s) across this campaign. Review and Start it.`, "success");
      onCreated(automation.id);
    } catch (e: any) {
      toast(e?.message || "Failed to create campaign-wide automation", "error");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <h3 className="text-base font-bold text-slate-900 dark:text-white">New Email Automation</h3>
        <p className="mt-1 text-[11px] text-slate-400">
          Covers every AI-recommended shopper across the whole campaign — shops are never picked or shown here.
        </p>

        <div className="mt-3 inline-flex rounded-xl bg-slate-100 p-1 dark:bg-slate-800/70">
          {(["active", "upcoming", "all"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setCampaignType(t)}
              className={classNames(
                "rounded-lg px-3.5 py-1.5 text-xs font-semibold transition",
                campaignType === t ? "bg-brand-600 text-white shadow" : "text-slate-500 hover:text-slate-800 dark:text-slate-400"
              )}
            >
              {t === "active" ? "Active Campaign" : t === "upcoming" ? "Upcoming Campaign" : "Entire Campaign"}
            </button>
          ))}
        </div>
        {campaignType === "all" && (
          <p className="mt-1.5 text-[11px] text-slate-400">
            Pick any campaign, active or upcoming — no need to filter by status first.
          </p>
        )}

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Campaign</label>
            {!eligibleCampaigns.length ? (
              <div className="input flex h-9 items-center text-sm text-slate-400">
                No {campaignType === "all" ? "active or upcoming" : campaignType} campaigns
              </div>
            ) : (
              <select className="input" value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
                {eligibleCampaigns.map((c: any) => (
                  <option key={c.id} value={c.id}>
                    {c.name}{campaignType === "all" ? ` (${cap(c.bucket)})` : ""}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div>
            <label className="label">Automation name</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="label">Wait between steps (days)</label>
            <input type="number" min={1} max={14} className="input" value={waitDaysInput} onChange={(e) => setWaitDaysInput(e.target.value)} />
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
            {batchSize * iterations} shopper(s) total reached; anyone beyond that stays queued, unsent). Each wave
            also gets its own email — Email Steps below will show {iterations} step(s) to match.
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
                  value={batchSizeInput}
                  onChange={(e) => setBatchSizeInput(e.target.value)}
                />
              </div>
              <div>
                <label className="label">Iterations (number of waves)</label>
                <input
                  type="number"
                  min={1}
                  max={52}
                  className="input"
                  value={iterationsInput}
                  onChange={(e) => setIterationsInput(e.target.value)}
                />
              </div>
            </div>
          )}
        </div>

        <div className="mt-4 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <label className="label flex items-center gap-2">
            <input type="checkbox" checked={voiceCallEnabled} onChange={(e) => setVoiceCallEnabled(e.target.checked)} />
            AI Voice Call Follow-Up
          </label>
          <p className="mt-1 text-[11px] text-slate-400">
            If a shopper never replies to any of the email steps above, place a real phone call — an AI
            voice conversation asks whether they're still interested. Requires Twilio to be configured
            server-side; if it isn't, this stays off with no effect on the email sequence.
          </p>
          {voiceCallEnabled && (
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <div>
                <label className="label">Wait after last email (days)</label>
                <input
                  type="number"
                  min={0}
                  max={30}
                  className="input"
                  value={voiceCallDelayInput}
                  onChange={(e) => setVoiceCallDelayInput(e.target.value)}
                />
              </div>
              <div>
                <label className="label">Retry gap if unanswered (days)</label>
                <input
                  type="number"
                  min={1}
                  max={30}
                  className="input"
                  value={voiceCallRetryGapInput}
                  onChange={(e) => setVoiceCallRetryGapInput(e.target.value)}
                />
              </div>
              <div>
                <label className="label">Max call attempts</label>
                <input
                  type="number"
                  min={1}
                  max={5}
                  className="input"
                  value={voiceCallMaxAttemptsInput}
                  onChange={(e) => setVoiceCallMaxAttemptsInput(e.target.value)}
                />
              </div>
            </div>
          )}
        </div>

        <div className="mt-4">
          <div className="label">
            Email steps{batchEnabled ? " (one per wave — change Iterations above to add or remove steps)" : ""}
          </div>
          <div className={classNames("grid gap-2", stepCount > 3 ? "sm:grid-cols-4" : "sm:grid-cols-3")}>
            {Array.from({ length: stepCount }, (_, i) => i + 1).map((step) => {
              const defaultName = step === 1 ? "Initial Invitation" : step === stepCount ? "Final Reminder" : "Reminder";
              return (
                <div key={step} className="rounded-lg border border-slate-200 p-2.5 dark:border-slate-700">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                    Step {step}{batchEnabled ? ` (wave ${step})` : ""}
                  </div>
                  <select
                    className="input mt-1 h-9 text-xs"
                    value={stepTemplates[step] || ""}
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
            Max {stepCount} email{stepCount > 1 ? "s" : ""} per shopper. Any shopper who clicks, visits the assignment
            page, accepts, or declines stops immediately — never reaches a later step.
          </p>
        </div>

        <div className="mt-4">
          <div className="flex items-center justify-between">
            <div className="label !mb-0">AI-recommended shoppers across this campaign</div>
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
          {campaignRecs.loading && !campaignRecs.data ? (
            <div className="mt-1.5 flex items-center gap-2 text-sm text-slate-400"><Spinner /> AI is matching shoppers…</div>
          ) : !candidates.length ? (
            <p className="mt-1.5 text-sm text-slate-400">No candidates found for any shop in this campaign.</p>
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
                    <div className="text-[11px] text-slate-400">
                      {r.city ? `${r.city} · ` : ""}{r.match_score}% match
                    </div>
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
  const [transcriptFor, setTranscriptFor] = useState<string | null>(null);

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
            {data.campaign_name} · {data.shop_name || "All shops"} · every {data.wait_days} day(s) · up to {data.max_steps} emails/shopper
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

      {data.voice_call_enabled && (
        <div className="card p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              📞 AI Voice Call Follow-Up
            </h3>
            <span className="text-[11px] text-slate-400">
              Wait {data.voice_call_delay_days}d after last email · retry every {data.voice_call_retry_gap_days}d · up to {data.voice_call_max_attempts} attempt(s)
            </span>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <KpiCard label="Calls Placed" value={d.voice_calls_placed} accent="indigo" />
            <KpiCard label="Interested" value={d.voice_call_interested} accent="emerald" />
            <KpiCard label="Not Interested" value={d.voice_call_not_interested} accent="rose" />
            <KpiCard label="Awaiting Call" value={d.voice_call_pending} accent="amber" />
          </div>
        </div>
      )}

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
              {data.voice_call_enabled && <th className="th">Voice Call</th>}
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
                {data.voice_call_enabled && (
                  <td className="td">
                    {s.voice_call_status ? (
                      <button
                        className="text-left"
                        onClick={() => setTranscriptFor(s.id)}
                        title="View call transcript"
                      >
                        <Badge className={VOICE_CALL_BADGE[s.voice_call_outcome || s.voice_call_status] || VOICE_CALL_BADGE.default}>
                          {s.voice_call_outcome ? cap(s.voice_call_outcome.replace("_", " ")) : cap(s.voice_call_status.replace("_", " "))}
                        </Badge>
                      </button>
                    ) : (
                      <span className="text-slate-300 dark:text-slate-600">—</span>
                    )}
                  </td>
                )}
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
                    {Array.from({ length: data.max_steps }, (_, i) => i + 1).map((st) => (
                      <option key={st} value={st}>Step {st}</option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
            {data.shoppers.length === 0 && (
              <tr>
                <td colSpan={data.voice_call_enabled ? 8 : 7} className="td py-8 text-center text-slate-400">No shoppers in this automation.</td>
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

      {transcriptFor && (
        <VoiceCallTranscriptModal
          automationId={automationId!}
          automationStateId={transcriptFor}
          onClose={() => setTranscriptFor(null)}
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

function VoiceCallTranscriptModal({
  automationId,
  automationStateId,
  onClose,
}: {
  automationId: string;
  automationStateId: string;
  onClose: () => void;
}) {
  const { data, loading, error } = useApi(() => api.automationVoiceCalls(automationId), [automationId]);
  const attempts = (data?.items || []).filter((l: any) => l.automation_state_id === automationStateId);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-5 shadow-2xl dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-200 pb-3 dark:border-slate-800">
          <h3 className="text-base font-bold text-slate-900 dark:text-white">Voice Call History</h3>
          <button className="btn-ghost" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {loading && !data ? (
          <div className="p-8"><Spinner /></div>
        ) : error ? (
          <div className="p-4 text-sm text-rose-500">{error}</div>
        ) : attempts.length === 0 ? (
          <p className="p-4 text-sm text-slate-400">No call attempts yet.</p>
        ) : (
          <div className="mt-3 space-y-4">
            {attempts.map((call: any) => (
              <div key={call.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
                  <span>{fmtDateTime(call.attempted_at)}</span>
                  <div className="flex items-center gap-2">
                    <Badge className={VOICE_CALL_BADGE[call.outcome || call.status] || VOICE_CALL_BADGE.default}>
                      {call.outcome ? cap(call.outcome.replace("_", " ")) : cap(call.status.replace("_", " "))}
                    </Badge>
                    {call.duration_seconds != null && <span>{call.duration_seconds}s</span>}
                  </div>
                </div>
                {call.error_message && (
                  <p className="mt-2 text-xs font-medium text-rose-600 dark:text-rose-400">{call.error_message}</p>
                )}
                {call.transcript?.length > 0 && (
                  <div className="mt-2 space-y-1.5">
                    {call.transcript.map((turn: any, i: number) => (
                      <div key={i} className={classNames("text-xs", turn.role === "assistant" ? "text-slate-700 dark:text-slate-200" : "text-brand-600 dark:text-brand-400")}>
                        <span className="font-semibold">{turn.role === "assistant" ? "AI: " : "Shopper: "}</span>
                        {turn.text}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <div className="mt-3 border-t border-slate-200 pt-3 text-right dark:border-slate-800">
          <button className="btn-secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
