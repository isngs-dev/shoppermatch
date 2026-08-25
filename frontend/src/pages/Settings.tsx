import { IconShield } from "../components/Icons";
import { Loading } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

export function Settings() {
  const { data, loading, error, reload } = useApi(() => api.settingsInfo());
  if (loading && !data) return <Loading label="Loading settings…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  const rows: [string, string][] = [
    ["Application", data.app_name],
    ["Tagline", data.tagline],
    ["Environment", data.environment],
    ["Public base URL", data.public_base_url],
    ["Database", data.database],
    ["Email provider", data.email_provider],
    ["From address", data.email_from],
    ["Tracking rate limit", `${data.tracking_rate_limit_per_minute} / min per client`],
    ["CORS origins", (data.cors_origins || []).join(", ")],
    ["Bulk email batch size", `${data.bulk_email_batch_size} sends`],
    ["Bulk email daily limit", `${data.bulk_email_daily_limit} sends / 24h`],
    ["Bulk email batch delay", `${data.bulk_email_batch_delay_seconds}s between batches`],
    ["Emails sent (last 24h)", `${data.emails_sent_last_24h} / ${data.bulk_email_daily_limit}`],
  ];

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="card p-6 lg:col-span-2">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Configuration</h2>
        <p className="mt-1 text-xs text-slate-400">
          Read-only view of non-secret runtime configuration (sourced from environment variables).
        </p>
        <dl className="mt-4 divide-y divide-slate-100 dark:divide-slate-800">
          {rows.map(([k, v]) => (
            <div key={k} className="flex items-center justify-between py-3">
              <dt className="text-sm text-slate-500 dark:text-slate-400">{k}</dt>
              <dd className="max-w-[60%] truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                {v}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="space-y-4">
        <div className="card p-6">
          <div className="flex items-center gap-2 text-emerald-600">
            <IconShield />
            <span className="text-sm font-semibold">Security</span>
          </div>
          <ul className="mt-3 space-y-2 text-sm text-slate-500 dark:text-slate-400">
            <li>• UUID tracking tokens, server-side validated</li>
            <li>• No raw database ids in public URLs</li>
            <li>• Rate limiting on tracking endpoints</li>
            <li>• Safe first-party redirects only</li>
            <li>• No raw IP addresses stored</li>
          </ul>
        </div>
        <div className="card p-6">
          <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Demo credentials
          </div>
          <div className="mt-2 rounded-lg bg-slate-50 px-3 py-2.5 text-sm text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
            admin@isn.com
            <br />
            isn-demo-2026
          </div>
        </div>
      </div>
    </div>
  );
}
