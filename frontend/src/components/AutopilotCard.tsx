import { useEffect, useState } from "react";
import { Badge, Spinner, useToast } from "./ui";
import { api } from "../lib/api";
import { classNames, fmtDateTime, fmtMoney } from "../lib/format";
import { useApi } from "../lib/useApi";

const MODES = [
  {
    key: "off",
    label: "Off",
    hint: "Nothing is recruited automatically — you pick shoppers yourself.",
  },
  {
    key: "review",
    label: "Review first",
    hint: "The AI finds the shoppers each shop needs, widens the radius and adds a bonus inside your limits, and prepares the invitations. You check them and send from Outreach.",
  },
  {
    key: "auto",
    label: "Fully automatic",
    hint: "Everything above, and the AI also emails the shoppers — each email written for that shopper.",
  },
] as const;

const STATE_META: Record<string, { label: string; badge: string }> = {
  staffed: { label: "Staffed", badge: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300" },
  partial: { label: "Partly filled", badge: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300" },
  needs_attention: { label: "Needs attention", badge: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300" },
  searching: { label: "Searching", badge: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300" },
  deferred: { label: "Next run", badge: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
  already_filled: { label: "Already filled", badge: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
};

const SOURCE_LABEL: Record<string, string> = {
  campaign: "set for this campaign",
  client: "your account-wide default",
  global: "the platform default",
  default: "the built-in default",
};

type Props = { campaignId: string; onChanged: () => void; onOpenOutreach: () => void };

export function AutopilotCard({ campaignId, onChanged, onOpenOutreach }: Props) {
  const toast = useToast();
  const cfg = useApi(() => api.autopilot(campaignId), [campaignId]);
  const [mode, setMode] = useState<string>("off");
  const [radius, setRadius] = useState("150");
  const [bonusX, setBonusX] = useState("2");
  const [minScore, setMinScore] = useState("40");
  const [perRun, setPerRun] = useState("100");
  const [fill, setFill] = useState(true);
  const [perShopper, setPerShopper] = useState("3");
  const [applyAll, setApplyAll] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState<"preview" | "run" | null>(null);
  const [confirmRun, setConfirmRun] = useState(false);
  const [report, setReport] = useState<any | null>(null);

  const eff = cfg.data?.effective;
  useEffect(() => {
    if (!eff) return;
    setMode(eff.mode);
    setRadius(String(eff.max_radius_km));
    setBonusX(String(eff.max_bonus_multiplier));
    setMinScore(String(eff.min_match_score));
    setPerRun(String(eff.max_invitations_per_run));
    setFill(!!eff.fill_every_shop);
    setPerShopper(String(eff.max_shops_per_shopper));
    setApplyAll(false);
  }, [
    eff?.mode,
    eff?.max_radius_km,
    eff?.max_bonus_multiplier,
    eff?.min_match_score,
    eff?.max_invitations_per_run,
    eff?.fill_every_shop,
    eff?.max_shops_per_shopper,
  ]);

  useEffect(() => {
    setReport(null);
    setConfirmRun(false);
  }, [campaignId]);

  if (cfg.loading && !cfg.data) return null;
  if (cfg.error || !eff) return null;

  const draft = {
    mode,
    max_radius_km: Number(radius),
    max_bonus_multiplier: Number(bonusX),
    min_match_score: Number(minScore),
    max_invitations_per_run: Number(perRun),
    fill_every_shop: fill,
    max_shops_per_shopper: Number(perShopper),
  };
  const dirty =
    mode !== eff.mode ||
    draft.max_radius_km !== eff.max_radius_km ||
    draft.max_bonus_multiplier !== eff.max_bonus_multiplier ||
    draft.min_match_score !== eff.min_match_score ||
    draft.max_invitations_per_run !== eff.max_invitations_per_run ||
    draft.fill_every_shop !== !!eff.fill_every_shop ||
    draft.max_shops_per_shopper !== eff.max_shops_per_shopper ||
    applyAll;
  const valid =
    draft.max_radius_km > 0 &&
    draft.max_bonus_multiplier >= 0 &&
    draft.min_match_score >= 0 &&
    draft.min_match_score <= 100 &&
    draft.max_invitations_per_run >= 1 &&
    draft.max_shops_per_shopper >= 1;
  const shown = report || cfg.data?.last_report;
  const isLast = !report && !!cfg.data?.last_report;

  async function save() {
    setSaving(true);
    try {
      if (applyAll) {
        // One default for every campaign of the account (existing and future); this campaign just follows it.
        await api.setAutopilotDefaults(draft);
        await api.setAutopilot(campaignId, {
          mode: null,
          max_radius_km: null,
          max_bonus_multiplier: null,
          min_match_score: null,
          max_invitations_per_run: null,
          fill_every_shop: null,
          max_shops_per_shopper: null,
        });
      } else {
        await api.setAutopilot(campaignId, draft);
      }
      await cfg.reload();
      toast(applyAll ? "Autopilot set for all your campaigns, including new ones." : "Autopilot saved for this campaign.", "success");
    } catch (e: any) {
      toast(e?.message || "Could not save Autopilot settings", "error");
    } finally {
      setSaving(false);
    }
  }

  async function run(dryRun: boolean) {
    setConfirmRun(false);
    setRunning(dryRun ? "preview" : "run");
    try {
      const res = await api.runAutopilot(campaignId, { dry_run: dryRun, mode: dryRun && eff.mode === "off" ? "review" : undefined });
      setReport(res);
      if (!dryRun) {
        onChanged();
        cfg.reload();
        const t = res.totals || {};
        toast(
          res.skipped
            ? res.skipped
            : `Autopilot invited ${t.invited ?? 0} shopper(s)` +
                (res.mode === "auto" ? `, emailed ${t.emailed ?? 0}` : " — ready to send from Outreach") +
                (t.needs_attention || t.partial
                  ? `; ${(t.needs_attention || 0) + (t.partial || 0)} shop(s) need attention`
                  : t.searching
                  ? `; still searching for shoppers for ${t.searching} shop(s) — it keeps retrying`
                  : ""),
          "success"
        );
      }
    } catch (e: any) {
      toast(e?.message || "Autopilot run failed", "error");
    } finally {
      setRunning(null);
    }
  }

  const modeMeta = MODES.find((m) => m.key === eff.mode)!;
  return (
    <div className="card space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">AI Autopilot</h3>
            <Badge
              className={
                eff.mode === "off"
                  ? "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                  : eff.mode === "review"
                  ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                  : "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
              }
            >
              {modeMeta.label}
            </Badge>
          </div>
          <p className="mt-0.5 max-w-2xl text-xs text-slate-500 dark:text-slate-400">
            Recommends the shoppers every shop needs, widens the radius or adds a bonus when there aren't enough — only inside
            the limits below — and prepares or sends the invitations. Currently {SOURCE_LABEL[eff.sources?.mode] || "default"}.
          </p>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        {MODES.map((m) => (
          <button
            key={m.key}
            type="button"
            onClick={() => setMode(m.key)}
            className={classNames(
              "rounded-lg border p-3 text-left transition",
              mode === m.key
                ? "border-brand-500 bg-brand-50 dark:border-brand-400 dark:bg-brand-950/30"
                : "border-slate-200 hover:border-slate-300 dark:border-slate-700 dark:hover:border-slate-600"
            )}
          >
            <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">{m.label}</div>
            <div className="mt-0.5 text-[11px] leading-snug text-slate-500 dark:text-slate-400">{m.hint}</div>
          </button>
        ))}
      </div>

      <details className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
        <summary className="cursor-pointer select-none text-xs font-semibold text-slate-700 dark:text-slate-200">
          Limits &amp; how far it goes
        </summary>
        <label className="mt-3 flex cursor-pointer items-start gap-2 text-xs text-slate-700 dark:text-slate-200">
          <input className="mt-0.5" type="checkbox" checked={fill} onChange={(e) => setFill(e.target.checked)} />
          <span>
            <span className="font-semibold">Fill every shop.</span> If the limits below aren't enough, keep going instead of
            stopping: let nearby shoppers take more than one shop, stretch the radius further (with a bonus that pays for the
            trip), and accept weaker matches. A shop nobody can fill yet is searched for again automatically.
          </span>
        </label>
        <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Field label="Comfortable radius (km)" value={radius} onChange={setRadius} hint="Widened freely up to this first." />
          <Field label="Max bonus (× shop pay)" value={bonusX} onChange={setBonusX} step="0.5" hint="0 = never add a bonus." />
          <Field label="Min match score (%)" value={minScore} onChange={setMinScore} hint="Weaker matches are never invited." />
          <Field label="Max invitations / run" value={perRun} onChange={setPerRun} hint="The rest follow in the next run." />
          <Field label="Max shops per shopper" value={perShopper} onChange={setPerShopper} hint="Only used when sharing shoppers." />
        </div>
        <p className="mt-3 text-[11px] text-slate-400">
          Always on, whatever you set: never more shoppers than a shop needs, never someone who already has (or declined) an
          invitation for that shop, never an opted-out shopper, never a bonus above its limit, and an awarded bonus is never changed.
        </p>
      </details>

      <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
        <input type="checkbox" checked={applyAll} onChange={(e) => setApplyAll(e.target.checked)} />
        Use these settings for <span className="font-semibold">all my campaigns</span>, including ones added later (e.g. synced through the API)
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary" onClick={save} disabled={!dirty || !valid || saving}>
          {saving ? <Spinner /> : null} Save
        </button>
        <button className="btn-secondary" onClick={() => run(true)} disabled={dirty || running !== null}>
          {running === "preview" ? <Spinner /> : null} Preview plan
        </button>
        {!confirmRun ? (
          <button
            className="btn-secondary"
            onClick={() => (eff.mode === "auto" ? setConfirmRun(true) : run(false))}
            disabled={dirty || eff.mode === "off" || running !== null}
            title={eff.mode === "off" ? "Switch Autopilot on to run it" : undefined}
          >
            {running === "run" ? <Spinner /> : null} Run now
          </button>
        ) : (
          <span className="flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-1.5 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
            This will email shoppers now.
            <button className="font-bold underline" onClick={() => run(false)}>
              Yes, run
            </button>
            <button className="underline" onClick={() => setConfirmRun(false)}>
              Cancel
            </button>
          </span>
        )}
        {dirty && <span className="text-[11px] text-slate-400">Save your changes to preview or run them.</span>}
      </div>

      {shown && <AutopilotReport report={shown} isLast={isLast} onOpenOutreach={onOpenOutreach} />}
    </div>
  );
}

function Field({ label, value, onChange, hint, step }: { label: string; value: string; onChange: (v: string) => void; hint: string; step?: string }) {
  return (
    <div>
      <label className="label">{label}</label>
      <input className="input h-9" type="number" min={0} step={step} value={value} onChange={(e) => onChange(e.target.value)} />
      <p className="mt-1 text-[10px] leading-tight text-slate-400">{hint}</p>
    </div>
  );
}

function actionText(a: any): string {
  if (a.type === "widen_radius") return `${a.stretch ? "Stretched" : "Widened"} radius ${a.from}→${a.to} km`;
  if (a.type === "share_shoppers") return `Let nearby shoppers take up to ${a.max_shops} shops`;
  if (a.type === "accept_weaker_matches") return "Accepted weaker matches";
  if (a.type === "bonus")
    return `${a.reason === "travel" ? "Travel bonus" : "Bonus"} ${fmtMoney(a.amount, a.currency)}${
      a.previous ? ` (was ${fmtMoney(a.previous, a.currency)})` : ""
    }`;
  return a.type;
}

function AutopilotReport({ report, isLast, onOpenOutreach }: { report: any; isLast: boolean; onOpenOutreach: () => void }) {
  const t = report.totals || {};
  const title = report.dry_run ? "Preview — nothing was changed or sent" : isLast ? "Last run" : "Run result";
  const filling = !!report.guardrails?.fill_every_shop;
  const attention = (t.needs_attention || 0) + (t.partial || 0) + (t.searching || 0);
  return (
    <div className="space-y-3 border-t border-slate-100 pt-4 dark:border-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          {title}
          {report.ran_at && !report.dry_run ? ` · ${fmtDateTime(report.ran_at)}` : ""}
          {report.trigger === "scheduler" ? " · automatic" : ""}
        </div>
        {!report.dry_run && (t.invited || 0) > 0 && (
          <button className="btn-secondary" onClick={onOpenOutreach}>
            {report.mode === "auto" ? "See in Outreach" : "Review & send in Outreach"} →
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 text-center sm:grid-cols-5">
        <Stat label={report.dry_run ? "Would invite" : "Invited"} value={t.invited ?? 0} />
        <Stat label={report.dry_run ? "Would email" : "Emailed"} value={report.mode === "auto" ? (report.dry_run ? t.invited ?? 0 : t.emailed ?? 0) : 0} />
        <Stat label="Radius widened" value={t.radius_widened ?? 0} />
        <Stat label="Bonuses" value={t.bonuses_set ?? 0} />
        <Stat
          label={filling ? "Still searching" : "Need attention"}
          value={attention}
          accent={attention ? (filling ? "text-indigo-600 dark:text-indigo-400" : "text-rose-600 dark:text-rose-400") : undefined}
        />
      </div>
      {report.ai_email_personalization && (
        <p className="text-[11px] text-emerald-600 dark:text-emerald-400">Each email's opening was written by AI for that shopper.</p>
      )}

      {report.skipped ? (
        <p className="text-sm text-slate-500">{report.skipped}</p>
      ) : report.shops.length === 0 ? (
        <p className="text-sm text-slate-500">Every shop already has all the shoppers it needs — nothing to do.</p>
      ) : (
        <div className="max-h-80 overflow-y-auto rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="min-w-full text-xs">
            <thead className="sticky top-0 bg-slate-50 text-left text-[10px] uppercase tracking-wide text-slate-400 dark:bg-slate-900">
              <tr>
                <th className="px-3 py-2">Shop</th>
                <th className="px-3 py-2">Result</th>
                <th className="px-3 py-2">What the AI did</th>
                <th className="px-3 py-2">Shoppers</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {report.shops.map((s: any) => {
                const meta = STATE_META[s.state] || STATE_META.deferred;
                return (
                  <tr key={s.shop_id} className="align-top">
                    <td className="px-3 py-2 font-medium text-slate-800 dark:text-slate-100">
                      {s.shop_name}
                      <div className="font-normal text-slate-400">needs {s.slots_open} of {s.required}</div>
                    </td>
                    <td className="px-3 py-2">
                      <Badge className={meta.badge}>{meta.label}</Badge>
                    </td>
                    <td className="px-3 py-2 text-slate-600 dark:text-slate-300">
                      {s.actions.length === 0 && !s.reason ? "Best matches were already in range" : null}
                      {s.actions.map((a: any, i: number) => (
                        <div key={i}>{actionText(a)}</div>
                      ))}
                      {s.reason && (
                        <div className={s.state === "searching" ? "text-indigo-600 dark:text-indigo-400" : "text-rose-600 dark:text-rose-400"}>
                          {s.reason}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slate-600 dark:text-slate-300">
                      {s.invited.length ? s.invited.map((p: any) => `${p.name} (${p.match_score}%)`).join(", ") : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800/60">
      <div className={classNames("text-lg font-bold text-slate-900 dark:text-white", accent)}>{value}</div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
    </div>
  );
}
