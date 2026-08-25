import { useState } from "react";
import { Badge, EmptyState, KpiCard, Loading, useToast } from "../components/ui";
import { IconClipboard, IconClock, IconTarget, IconUsers } from "../components/Icons";
import { api } from "../lib/api";
import { fmtDateTime, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

export function ClientActivity() {
  const { data, loading, error, reload } = useApi(() => api.adminClientActivitySummary());
  const [selected, setSelected] = useState<{ id: string; company: string } | null>(null);
  const toast = useToast();
  const [exporting, setExporting] = useState<string | null>(null);

  if (loading && !data) return <Loading label="Loading client activity…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  const items = data.items as any[];
  const activeClients = items.filter((i) => i.status === "active").length;
  const totalActions = items.reduce((s, i) => s + i.action_count, 0);
  const neverLoggedIn = items.filter((i) => !i.last_login).length;

  async function doExport(format: "csv" | "xlsx" | "pdf") {
    setExporting(format);
    try {
      await api.exportAdminClientActivity(format);
    } catch (e: any) {
      toast(e?.message || "Export failed", "error");
    } finally {
      setExporting(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Client Activity</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Every action a client takes in their portal — invitations sent, campaigns viewed, password changes,
            account changes — tracked here, sourced from the same audit trail as Audit Logs.
          </p>
        </div>
        <div className="flex gap-1">
          {(["pdf", "xlsx", "csv"] as const).map((fmt) => (
            <button
              key={fmt}
              className="btn-ghost !px-2.5 !py-1.5 text-xs uppercase"
              disabled={exporting === fmt}
              onClick={() => doExport(fmt)}
            >
              {exporting === fmt ? "…" : `Export ${fmt}`}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="Client Logins" value={items.length} icon={<IconUsers width={18} />} accent="brand" />
        <KpiCard label="Active Accounts" value={activeClients} icon={<IconTarget width={18} />} accent="emerald" />
        <KpiCard label="Total Actions Logged" value={totalActions} icon={<IconClipboard width={18} />} accent="indigo" />
        <KpiCard label="Never Logged In" value={neverLoggedIn} icon={<IconClock width={18} />} accent="amber" />
      </div>

      {items.length === 0 ? (
        <div className="card">
          <EmptyState title="No client logins yet" hint="Create one from Users → + New Client." />
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="min-w-full">
            <thead className="border-b border-slate-100 dark:border-slate-800">
              <tr>
                <th className="th">Client</th>
                <th className="th">Status</th>
                <th className="th">Last Login</th>
                <th className="th text-center">Actions Logged</th>
                <th className="th">Most Recent Activity</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
              {items.map((i) => (
                <tr
                  key={i.user_id}
                  className="cursor-pointer transition hover:bg-slate-50 dark:hover:bg-slate-800/40"
                  onClick={() => i.client_id && setSelected({ id: i.client_id, company: i.company || i.email })}
                >
                  <td className="td font-medium text-slate-800 dark:text-slate-100">
                    {i.company || "—"}
                    <div className="text-[11px] font-normal text-slate-400">{i.email}</div>
                  </td>
                  <td className="td">
                    <Badge className={statusBadgeClass(i.status === "active" ? "accepted" : "created")}>
                      {i.status}
                    </Badge>
                  </td>
                  <td className="td text-slate-500">{i.last_login ? fmtDateTime(i.last_login) : "Never"}</td>
                  <td className="td text-center font-semibold text-slate-700 dark:text-slate-200">
                    {i.action_count}
                  </td>
                  <td className="td text-slate-500">
                    {i.last_action_summary ? (
                      <>
                        <div className="text-slate-700 dark:text-slate-200">{i.last_action_summary}</div>
                        <div className="text-[11px] text-slate-400">{fmtDateTime(i.last_action_at)}</div>
                      </>
                    ) : (
                      "No activity yet"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <ClientActivityDrawer clientId={selected.id} company={selected.company} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function ClientActivityDrawer({
  clientId,
  company,
  onClose,
}: {
  clientId: string;
  company: string;
  onClose: () => void;
}) {
  const { data, loading, error, reload } = useApi(() => api.adminClientActivityDetail(clientId), [clientId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-900 dark:text-white">{company} — Activity</h3>
          <button className="btn-ghost" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="mt-4">
          {loading && !data ? (
            <Loading label="Loading activity…" />
          ) : error ? (
            <ErrorBox message={error} onRetry={reload} />
          ) : data.items.length === 0 ? (
            <EmptyState title="No activity logged for this client yet" />
          ) : (
            <div className="space-y-2">
              {data.items.map((a: any) => (
                <div key={a.id} className="rounded-lg border border-slate-100 p-3 text-sm dark:border-slate-800">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="badge bg-slate-100 font-mono text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {a.action}
                    </span>
                    <span className="text-[11px] text-slate-400">{fmtDateTime(a.created_at)}</span>
                  </div>
                  {a.summary && <p className="mt-1.5 text-slate-600 dark:text-slate-300">{a.summary}</p>}
                  {a.entity_type && (
                    <p className="mt-1 text-[11px] text-slate-400">
                      {a.entity_type}
                      {a.entity_id ? ` · ${a.entity_id}` : ""}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
