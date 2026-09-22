// Deliberately its own top-level page, separate from Outreach (Send
// Invitation only, now). Outreach only makes sense scoped to one campaign
// (reached via that campaign's own Outreach tab); Email Automation runs
// across whichever campaign+shop you pick from its own selector, so it
// isn't campaign-scoped the same way and gets its own top-level nav entry.
//
// Template management (EmailTemplatesPanel) lives here rather than on
// Outreach — templates are consumed by both manual sends and automation
// steps, so they belong with neither exclusively, and Automation is the
// more natural home since every automation step picks a template directly.
//
// Tracking lives here too — the same Sent/Opened/Clicked/Source table every
// campaign's own Tracking tab already shows, filtered to automation-sent
// invitations only and spanning every campaign this client owns (Email
// Automation isn't scoped to one campaign, so neither is this). It's the
// exact same Invitation rows + tracking pipeline (real click-through
// redirect, real open pixel) — this view just filters to automation_id is
// not null. The same rows are also visible in ISN Admin Tracking, tagged
// with which automation/step sent them.
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { InvitationDrawer } from "../../components/InvitationDrawer";
import { Badge, CheckCell, Loading } from "../../components/ui";
import { api } from "../../lib/api";
import { classNames, fmtDateTime, statusBadgeClass } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { BulkSendStatusCard } from "../Outreach";
import { BulkVoiceCallPanel, EmailAutomationPanel, VOICE_CALL_BADGE } from "../EmailAutomation";
import { EmailTemplatesPanel } from "../EmailTemplates";
import { ErrorBox } from "../Dashboard";

const TABS = [
  { key: "automations", label: "Automations" },
  { key: "bulk-call", label: "Bulk Voice Call" },
  { key: "tracking", label: "Email Tracking" },
  { key: "call-tracking", label: "Call Tracking" },
  { key: "templates", label: "Templates" },
] as const;

export function ClientEmailAutomation() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = (searchParams.get("tab") as (typeof TABS)[number]["key"]) || "automations";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900 dark:text-white">Email Automation</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Configure and run multi-step outreach sequences for AI-recommended shoppers, across any campaign.
        </p>
      </div>

      <div className="flex gap-1 overflow-x-auto rounded-xl bg-slate-100 p-1 dark:bg-slate-800/70">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setSearchParams(t.key === "automations" ? {} : { tab: t.key })}
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

      {activeTab === "templates" ? (
        <div className="card p-5">
          <EmailTemplatesPanel compact />
        </div>
      ) : activeTab === "tracking" ? (
        <AutomationTrackingTab />
      ) : activeTab === "call-tracking" ? (
        <CallTrackingTab />
      ) : activeTab === "bulk-call" ? (
        <BulkVoiceCallPanel />
      ) : (
        <>
          <BulkSendStatusCard />
          <EmailAutomationPanel compact />
        </>
      )}
    </div>
  );
}

function AutomationTrackingTab() {
  const { data, loading, error, reload } = useApi(() => api.invitations({ automation_only: true, limit: 500 }));
  const [selected, setSelected] = useState<string | null>(null);
  if (loading && !data) return <Loading label="Loading automation tracking…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  const items = data?.items || [];

  return (
    <>
      <div className="card overflow-x-auto">
        <div className="flex items-center justify-between border-b border-slate-100 p-4 dark:border-slate-800">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Automation-sent emails
            <span className="ml-2 text-xs font-normal text-slate-400">{items.length}</span>
          </h2>
          <button className="btn-secondary h-8 px-2.5 text-xs" onClick={reload}>
            Refresh
          </button>
        </div>
        <table className="min-w-full">
          <thead className="border-b border-slate-100 dark:border-slate-800">
            <tr>
              <th className="th">Shopper</th>
              <th className="th hidden md:table-cell">Email</th>
              <th className="th hidden lg:table-cell">Campaign</th>
              <th className="th hidden xl:table-cell">Automation</th>
              <th className="th text-center">Sent</th>
              <th className="th text-center">Opened</th>
              <th className="th text-center">Clicked</th>
              <th className="th text-center">Visited</th>
              <th className="th">Response</th>
              <th className="th hidden lg:table-cell">Source</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
            {items.map((r: any) => (
              <tr
                key={r.id}
                className="cursor-pointer transition-colors hover:bg-brand-50/70 dark:hover:bg-brand-950/30"
                onClick={() => setSelected(r.id)}
              >
                <td className="td font-medium text-slate-800 dark:text-slate-100">
                  {r.shopper_name}
                  <div className="text-[11px] font-normal text-slate-400">{r.reference}</div>
                </td>
                <td className="td hidden text-slate-500 md:table-cell">{r.shopper_email}</td>
                <td className="td hidden text-slate-500 lg:table-cell">{r.campaign_name}</td>
                <td className="td hidden xl:table-cell">
                  {r.automation_id ? (
                    <span className="badge bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
                      {r.automation_name} · Step {r.automation_step}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.sent_at} /></div></td>
                <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.opened_at} /></div></td>
                <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.clicked_at} /></div></td>
                <td className="td text-center"><div className="flex justify-center"><CheckCell on={!!r.visited_at} /></div></td>
                <td className="td">
                  <Badge className={statusBadgeClass(r.response || "pending")}>{r.response ? cap(r.response) : "Pending"}</Badge>
                </td>
                <td className="td hidden lg:table-cell">
                  <span className="badge bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300">
                    Client Email / SendGrid
                  </span>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={10} className="td py-10 text-center text-slate-400">
                  No automation-sent emails yet — start a sequence from the Automations tab.
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

// Every real call this client has placed — a named shopper's Real AI Call /
// scheduled follow-up AND an ad-hoc Bulk Voice Call number, merged into one
// chronological list (each row tagged "Automation" or "Bulk" so the source
// is never ambiguous) — deliberately its own tab, separate from Email
// Tracking above, since a phone conversation and an email open/click are
// different channels with different outcomes to review.
function CallTrackingTab() {
  const { data, loading, error, reload } = useApi(() => api.callTracking());
  const [selected, setSelected] = useState<any | null>(null);
  if (loading && !data) return <Loading label="Loading call tracking…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  const items = data?.items || [];

  return (
    <>
      <div className="card overflow-x-auto">
        <div className="flex items-center justify-between border-b border-slate-100 p-4 dark:border-slate-800">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Voice calls
            <span className="ml-2 text-xs font-normal text-slate-400">{items.length}</span>
          </h2>
          <button className="btn-secondary h-8 px-2.5 text-xs" onClick={reload}>
            Refresh
          </button>
        </div>
        <table className="min-w-full text-sm">
          <thead className="border-b border-slate-100 dark:border-slate-800">
            <tr>
              <th className="th">Shopper / Number</th>
              <th className="th hidden lg:table-cell">Campaign</th>
              <th className="th">Source</th>
              <th className="th">Status</th>
              <th className="th">Outcome</th>
              <th className="th hidden md:table-cell">When</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
            {items.map((r: any) => (
              <tr
                key={r.id}
                className="cursor-pointer transition-colors hover:bg-brand-50/70 dark:hover:bg-brand-950/30"
                onClick={() => setSelected(r)}
              >
                <td className="td font-medium text-slate-800 dark:text-slate-100">
                  {r.shopper_name || <span className="font-mono font-normal">{r.phone_number}</span>}
                  {r.shopper_name && (
                    <div className="text-[11px] font-normal text-slate-400">{r.phone_number}</div>
                  )}
                </td>
                <td className="td hidden text-slate-500 lg:table-cell">{r.campaign_name || "—"}</td>
                <td className="td">
                  <span
                    className={classNames(
                      "badge",
                      r.kind === "automation"
                        ? "bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300"
                        : "bg-violet-50 text-violet-700 dark:bg-violet-950 dark:text-violet-300"
                    )}
                  >
                    {r.kind === "automation" ? "Automation" : "Bulk"}
                  </span>
                </td>
                <td className="td">
                  <Badge className={VOICE_CALL_BADGE[(r.status || "").replace("-", "_")] || VOICE_CALL_BADGE.default}>
                    {cap((r.status || "—").replace(/[-_]/g, " "))}
                  </Badge>
                </td>
                <td className="td text-slate-500">{r.outcome ? cap(r.outcome.replace("_", " ")) : "—"}</td>
                <td className="td hidden text-slate-500 md:table-cell">{r.attempted_at ? fmtDateTime(r.attempted_at) : "—"}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={6} className="td py-10 text-center text-slate-400">
                  No calls placed yet — try "Real AI Call" on a shopper, or start a Bulk Voice Call.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {selected && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60" onClick={() => setSelected(null)} />
          <div className="relative max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-5 shadow-2xl dark:bg-slate-900">
            <div className="flex items-center justify-between border-b border-slate-200 pb-3 dark:border-slate-800">
              <div>
                <h3 className="text-base font-bold text-slate-900 dark:text-white">
                  {selected.shopper_name || selected.phone_number}
                </h3>
                <p className="text-xs text-slate-400">
                  {selected.phone_number}
                  {selected.campaign_name ? ` · ${selected.campaign_name}` : ""}
                </p>
              </div>
              <button className="btn-ghost" onClick={() => setSelected(null)} aria-label="Close">✕</button>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <Badge className={VOICE_CALL_BADGE[(selected.status || "").replace("-", "_")] || VOICE_CALL_BADGE.default}>
                {cap((selected.status || "—").replace(/[-_]/g, " "))}
              </Badge>
              {selected.attempted_at && <span>{fmtDateTime(selected.attempted_at)}</span>}
              {selected.duration_seconds != null && <span>{selected.duration_seconds}s</span>}
            </div>
            {selected.error_message && (
              <p className="mt-2 text-xs font-medium text-rose-600 dark:text-rose-400">{selected.error_message}</p>
            )}
            {selected.transcript?.length > 0 ? (
              <div className="mt-3 space-y-1.5">
                {selected.transcript.map((turn: any, i: number) => (
                  <div
                    key={i}
                    className={classNames(
                      "text-xs",
                      turn.role === "assistant" ? "text-slate-700 dark:text-slate-200" : "text-brand-600 dark:text-brand-400"
                    )}
                  >
                    <span className="font-semibold">{turn.role === "assistant" ? "AI: " : "Caller: "}</span>
                    {turn.text}
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-xs text-slate-400">No transcript yet.</p>
            )}
            <div className="mt-3 border-t border-slate-200 pt-3 text-right dark:border-slate-800">
              <button className="btn-secondary" onClick={() => setSelected(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function cap(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
