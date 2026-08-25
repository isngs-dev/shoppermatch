import { useState } from "react";
import { IconCheck, IconPlug, IconShield, IconX } from "../components/Icons";
import { Avatar, Badge, Loading, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";
import { useAuth } from "../lib/auth";

const STATUS_META: Record<string, { label: string; className: string }> = {
  connected: { label: "Connected", className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300" },
  demo: { label: "Demo", className: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300" },
  disconnected: { label: "Disconnected", className: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
  configuration_required: { label: "Configuration Required", className: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300" },
  error: { label: "Connection Failed", className: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300" },
  testing: { label: "Testing…", className: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300" },
};

// Per-provider configuration fields (spec sections 7/21/23/25/27).
const FIELDS: Record<string, { key: string; label: string; secret?: boolean; placeholder?: string }[]> = {
  sassie: [
    { key: "api_base_url", label: "API Base URL", placeholder: "https://api.sassie.com" },
    { key: "api_key", label: "API Key", secret: true, placeholder: "••••••••••••" },
    { key: "client_id", label: "Client ID" },
  ],
  email: [
    { key: "from_name", label: "From Name", placeholder: "ISN Shopper Recruitment" },
    { key: "from_email", label: "From Email", placeholder: "verified sender address" },
    { key: "api_key", label: "SendGrid API Key", secret: true, placeholder: "••••••••••••" },
  ],
  ai: [
    { key: "provider", label: "Provider", placeholder: "e.g. gemini, openai, local" },
    { key: "model", label: "Model", placeholder: "e.g. gemini-1.5-flash" },
    { key: "api_key", label: "API Key", secret: true, placeholder: "••••••••••••" },
  ],
  maps: [{ key: "api_key", label: "Google Maps API Key", secret: true, placeholder: "••••••••••••" }],
  sms: [
    { key: "sms_provider", label: "SMS Provider", placeholder: "e.g. twilio" },
    { key: "sender", label: "Sender" },
    { key: "api_key", label: "API Key", secret: true, placeholder: "••••••••••••" },
  ],
};

export function Integrations() {
  const { user } = useAuth();
  const toast = useToast();
  const integrations = useApi(() => api.integrations());
  const syncLogs = useApi(() => api.syncLogs());

  const [configuring, setConfiguring] = useState<any | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [showSyncConfirm, setShowSyncConfirm] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState<string[]>([]);

  async function testConnection(provider: string) {
    setTesting(provider);
    try {
      const res = await api.testIntegration(provider);
      toast(res.message || (res.connected ? "Connection successful." : "Connection failed."), res.connected ? "success" : "error");
      integrations.reload();
    } catch (e: any) {
      toast(e?.message || "Test failed", "error");
    } finally {
      setTesting(null);
    }
  }

  async function startSync() {
    setShowSyncConfirm(false);
    setSyncing(true);
    setSyncProgress(["Connecting to SASSIE…", "Fetching campaigns, shops and shoppers…"]);
    try {
      const log = await api.startSassieSync();
      setSyncProgress((p) => [...p, "Validating and upserting into PostgreSQL…"]);
      if (log.status === "success") {
        setSyncProgress((p) => [
          ...p,
          `Synchronization completed: ${log.campaigns.created + log.campaigns.updated} campaigns, ` +
            `${log.shops.created + log.shops.updated} shops, ${log.shoppers.created + log.shoppers.updated} shoppers.`,
        ]);
        toast("SASSIE synchronization completed.", "success");
      } else if (log.status === "partial") {
        setSyncProgress((p) => [...p, `Synchronization completed with ${log.errors.length} warning(s).`]);
        toast("Synchronization completed with warnings — see errors below.", "info");
      } else {
        setSyncProgress((p) => [...p, `Synchronization failed: ${log.error_message}`]);
        toast(`Synchronization failed: ${log.error_message}`, "error");
      }
      integrations.reload();
      syncLogs.reload();
    } catch (e: any) {
      setSyncProgress((p) => [...p, `Synchronization failed: ${e?.message || "unknown error"}`]);
      toast(e?.message || "Synchronization failed", "error");
    } finally {
      setSyncing(false);
    }
  }

  if (integrations.loading && !integrations.data) return <Loading label="Loading integrations…" />;
  if (integrations.error) return <ErrorBox message={integrations.error} onRetry={integrations.reload} />;

  const sassie = integrations.data.items.find((i: any) => i.provider === "sassie");
  const latestSync = syncLogs.data?.items?.[0];

  return (
    <div className="space-y-8">
      {/* 1. User Access */}
      <section>
        <h2 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-100">User Access</h2>
        <div className="card flex items-center gap-3 p-4">
          <Avatar name={user?.name} className="h-10 w-10" />
          <div>
            <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">{user?.name}</div>
            <div className="text-xs text-slate-400">{user?.email}</div>
          </div>
          <Badge className="ml-auto bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300">
            <IconShield width={12} height={12} /> {user?.role}
          </Badge>
        </div>
        <p className="mt-1.5 text-[11px] text-slate-400">
          Only authenticated admin users can configure integrations, view/edit credentials, or start
          synchronization — enforced by the same bearer-token auth used across the app.
        </p>
      </section>

      {/* 2. Integration Management */}
      <section>
        <h2 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-100">Integration Management</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {integrations.data.items.map((it: any) => {
            const meta = STATUS_META[it.status] || STATUS_META.disconnected;
            return (
              <div key={it.provider} className="card flex flex-col p-5">
                <div className="flex items-start justify-between">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 text-slate-500 dark:bg-slate-800">
                    <IconPlug />
                  </div>
                  <Badge className={meta.className}>{meta.label}</Badge>
                </div>
                <h3 className="mt-3 text-base font-semibold text-slate-900 dark:text-white">{it.display_name}</h3>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {it.configuration?.description || ""}
                </p>
                {it.last_tested_at && (
                  <p className="mt-2 text-[11px] text-slate-400">Last tested {fmtDateTime(it.last_tested_at)}</p>
                )}
                {it.last_error && it.status === "error" && (
                  <p className="mt-1 text-[11px] text-rose-600 dark:text-rose-400">{it.last_error}</p>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  <button className="btn-secondary" onClick={() => setConfiguring(it)}>
                    Configure
                  </button>
                  <button className="btn-secondary" onClick={() => testConnection(it.provider)} disabled={testing === it.provider}>
                    {testing === it.provider ? <Spinner /> : null} Test Connection
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* 3. Data Synchronization */}
      <section>
        <h2 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-100">Data Synchronization</h2>
        <div className="card p-5">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <div className="text-xs text-slate-400">Source</div>
              <div className="font-semibold text-slate-800 dark:text-slate-100">SASSIE</div>
            </div>
            <div>
              <div className="text-xs text-slate-400">Last Synchronization</div>
              <div className="font-semibold text-slate-800 dark:text-slate-100">
                {sassie?.last_sync_at ? fmtDateTime(sassie.last_sync_at) : "Never"}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-400">Status</div>
              <div className="font-semibold text-slate-800 dark:text-slate-100">
                {latestSync ? (latestSync.status === "success" ? "✓ Successful" : latestSync.status) : "—"}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-400">Records</div>
              <div className="font-semibold text-slate-800 dark:text-slate-100">
                {latestSync
                  ? `${latestSync.campaigns.fetched} campaigns · ${latestSync.shops.fetched} shops · ${latestSync.shoppers.fetched} shoppers`
                  : "—"}
              </div>
            </div>
          </div>

          {syncing && (
            <div className="mt-4 space-y-1.5 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800/50">
              <div className="font-semibold text-slate-700 dark:text-slate-200">Synchronizing SASSIE…</div>
              {syncProgress.map((line, i) => (
                <div key={i} className="text-slate-500 dark:text-slate-400">
                  ✓ {line}
                </div>
              ))}
            </div>
          )}

          <button className="btn-primary mt-4" onClick={() => setShowSyncConfirm(true)} disabled={syncing}>
            {syncing ? <Spinner /> : null} Start Synchronization
          </button>
        </div>
      </section>

      {/* 4. Synchronization History */}
      <section>
        <h2 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-100">Synchronization History</h2>
        {syncLogs.loading && !syncLogs.data ? (
          <Loading label="Loading history…" />
        ) : !syncLogs.data?.items.length ? (
          <div className="card p-8 text-center text-sm text-slate-400">No synchronizations yet.</div>
        ) : (
          <div className="space-y-3">
            {syncLogs.data.items.map((log: any) => (
              <div key={log.id} className="card p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                    {fmtDateTime(log.started_at)} · {log.provider.toUpperCase()}
                  </div>
                  <Badge
                    className={
                      log.status === "success"
                        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                        : log.status === "failed"
                        ? "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300"
                        : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                    }
                  >
                    {log.status === "success" ? "✓ Successful" : log.status}
                  </Badge>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
                  <SyncStat label="Campaigns" v={log.campaigns} />
                  <SyncStat label="Shops" v={log.shops} />
                  <SyncStat label="Shoppers" v={log.shoppers} />
                </div>
                {log.errors?.length > 0 && (
                  <div className="mt-2 text-xs text-amber-600 dark:text-amber-400">{log.errors.length} warning(s)</div>
                )}
                {log.error_message && (
                  <div className="mt-2 text-xs text-rose-600 dark:text-rose-400">{log.error_message}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {configuring && (
        <ConfigureModal
          integration={configuring}
          onClose={() => setConfiguring(null)}
          onSaved={() => {
            setConfiguring(null);
            integrations.reload();
          }}
        />
      )}

      {showSyncConfirm && (
        <SyncConfirmModal onCancel={() => setShowSyncConfirm(false)} onConfirm={startSync} />
      )}
    </div>
  );
}

function SyncStat({ label, v }: { label: string; v: { fetched: number; created: number; updated: number } }) {
  return (
    <div className="rounded-lg bg-slate-50 p-2.5 dark:bg-slate-800/50">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-0.5 text-slate-700 dark:text-slate-200">
        {v.fetched} fetched · {v.created} created · {v.updated} updated
      </div>
    </div>
  );
}

function ConfigureModal({
  integration,
  onClose,
  onSaved,
}: {
  integration: any;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const fields = FIELDS[integration.provider] || [];
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.filter((f) => !f.secret).map((f) => [f.key, integration.configuration?.[f.key] || ""]))
  );
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [testEmail, setTestEmail] = useState("");
  const [sendingTest, setSendingTest] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await api.updateIntegrationConfig(integration.provider, { configuration: values, secrets });
      toast(`${integration.display_name} configuration saved.`, "success");
      onSaved();
    } catch (e: any) {
      toast(e?.message || "Failed to save configuration", "error");
    } finally {
      setSaving(false);
    }
  }

  async function sendTest() {
    if (!testEmail.trim()) return;
    setSendingTest(true);
    try {
      const res = await api.sendTestEmail(testEmail.trim());
      toast(res.delivered ? `Test email sent to ${testEmail.trim()}.` : `Send failed: ${res.detail}`, res.delivered ? "success" : "error");
    } catch (e: any) {
      toast(e?.message || "Failed to send test email", "error");
    } finally {
      setSendingTest(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full max-w-md rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-900 dark:text-white">{integration.display_name} Configuration</h3>
          <button className="btn-ghost" onClick={onClose} aria-label="Close">
            <IconX />
          </button>
        </div>

        <div className="mt-4 space-y-3">
          {fields.map((f) => (
            <div key={f.key}>
              <label className="label">{f.label}</label>
              <input
                className="input"
                type={f.secret ? "password" : "text"}
                placeholder={f.placeholder}
                value={f.secret ? secrets[f.key] || "" : values[f.key] || ""}
                onChange={(e) =>
                  f.secret
                    ? setSecrets((s) => ({ ...s, [f.key]: e.target.value }))
                    : setValues((v) => ({ ...v, [f.key]: e.target.value }))
                }
              />
              {f.secret && integration.has_secrets && !secrets[f.key] && (
                <p className="mt-1 text-[11px] text-slate-400">A value is already saved — leave blank to keep it.</p>
              )}
            </div>
          ))}
          {integration.provider === "sassie" && (
            <div>
              <label className="label">Environment</label>
              <select
                className="input"
                value={values.environment || "demo"}
                onChange={(e) => setValues((v) => ({ ...v, environment: e.target.value }))}
              >
                <option value="demo">Demo</option>
                <option value="staging">Staging</option>
                <option value="production">Production</option>
              </select>
              <p className="mt-1 text-[11px] text-slate-400">
                Leave API Base URL blank to keep using the built-in demo SASSIE adapter.
              </p>
            </div>
          )}
        </div>

        <button className="btn-primary mt-5 w-full" onClick={save} disabled={saving}>
          {saving ? <Spinner /> : null} Save Configuration
        </button>

        {integration.provider === "email" && (
          <div className="mt-4 border-t border-slate-200 pt-4 dark:border-slate-800">
            <label className="label">Test Email Address</label>
            <div className="flex gap-2">
              <input
                className="input"
                type="email"
                placeholder="you@example.com"
                value={testEmail}
                onChange={(e) => setTestEmail(e.target.value)}
              />
              <button className="btn-secondary shrink-0" onClick={sendTest} disabled={sendingTest || !testEmail.trim()}>
                {sendingTest ? <Spinner /> : null} Send Test Email
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SyncConfirmModal({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} />
      <div className="relative w-full max-w-sm rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <h3 className="text-base font-bold text-slate-900 dark:text-white">Start Synchronization?</h3>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          This will retrieve the latest data from SASSIE and synchronize it with ShopperMatch.AI.
        </p>
        <ul className="mt-3 space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <li className="flex items-center gap-2">
            <IconCheck width={14} height={14} className="text-emerald-500" /> Campaigns
          </li>
          <li className="flex items-center gap-2">
            <IconCheck width={14} height={14} className="text-emerald-500" /> Shops
          </li>
          <li className="flex items-center gap-2">
            <IconCheck width={14} height={14} className="text-emerald-500" /> Shoppers
          </li>
        </ul>
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn-primary" onClick={onConfirm}>
            Start Synchronization
          </button>
        </div>
      </div>
    </div>
  );
}
