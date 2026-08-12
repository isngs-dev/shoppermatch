import { Loading } from "../components/ui";
import { api } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

export function AuditLogs() {
  const { data, loading, error, reload } = useApi(() => api.auditLogs());
  if (loading && !data) return <Loading label="Loading audit logs…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <div className="card overflow-x-auto">
      <table className="min-w-full">
        <thead className="border-b border-slate-100 dark:border-slate-800">
          <tr>
            <th className="th">Time</th>
            <th className="th">Actor</th>
            <th className="th">Action</th>
            <th className="th">Entity</th>
            <th className="th">Summary</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
          {data.items.map((a: any) => (
            <tr key={a.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
              <td className="td whitespace-nowrap text-slate-500">{fmtDateTime(a.created_at)}</td>
              <td className="td">{a.actor}</td>
              <td className="td">
                <span className="badge bg-slate-100 font-mono text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {a.action}
                </span>
              </td>
              <td className="td text-slate-500">
                {a.entity_type}
                {a.entity_id ? ` · ${a.entity_id}` : ""}
              </td>
              <td className="td">{a.summary}</td>
            </tr>
          ))}
          {data.items.length === 0 && (
            <tr>
              <td colSpan={5} className="td py-10 text-center text-slate-400">
                No audit entries yet. Generate an invitation to create one.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
