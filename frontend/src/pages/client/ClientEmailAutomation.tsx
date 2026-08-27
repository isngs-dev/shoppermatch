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
import { classNames, statusBadgeClass } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { BulkSendStatusCard } from "../Outreach";
import { EmailAutomationPanel } from "../EmailAutomation";
import { EmailTemplatesPanel } from "../EmailTemplates";
import { ErrorBox } from "../Dashboard";

const TABS = [
  { key: "automations", label: "Automations" },
  { key: "tracking", label: "Tracking" },
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
                className="cursor-pointer transition hover:bg-slate-50 dark:hover:bg-slate-800/40"
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

function cap(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
