import { Link } from "react-router-dom";
import { EmptyState, Loading } from "../../components/ui";
import { api } from "../../lib/api";
import { useApi } from "../../lib/useApi";
import { ErrorBox } from "../Dashboard";

export function ClientInsights() {
  const { data, loading, error, reload } = useApi(() => api.clientInsights());
  if (loading && !data) return <Loading label="Loading insights…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Insights</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          AI-generated, plain-English summaries of how your active and upcoming campaigns are progressing.
        </p>
      </div>

      {!data.items.length ? (
        <div className="card">
          <EmptyState title="No active or upcoming campaigns" hint="Insights appear here once a campaign is underway." />
        </div>
      ) : (
        <div className="space-y-3">
          {data.items.map((ins: any) => (
            <Link
              key={ins.campaign_id}
              to={`/client/campaigns/${ins.campaign_id}`}
              className="card block border p-5 transition hover:shadow-md"
            >
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-slate-900 dark:text-white">{ins.campaign_name}</h3>
                <span className="text-xs font-semibold text-slate-400">Readiness {ins.readiness}%</span>
              </div>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">✨ {ins.message}</p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
