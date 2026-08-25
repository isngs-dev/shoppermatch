import { useState } from "react";
import { Badge, CopyButton, EmptyState, Loading, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
import { fmtDateTime, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

const TABS = [
  { key: "clients", label: "Client Users" },
  { key: "shoppers", label: "Shoppers" },
];

export function AdminUsers() {
  const [tab, setTab] = useState<"clients" | "shoppers">("clients");
  const toast = useToast();
  const [exporting, setExporting] = useState<string | null>(null);

  async function doExport(fn: () => Promise<void>, key: string) {
    setExporting(key);
    try {
      await fn();
    } catch (e: any) {
      toast(e?.message || "Export failed", "error");
    } finally {
      setExporting(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">User Management</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Client-portal logins and the shopper directory, with real activity from outreach data.
          </p>
        </div>
        <div className="flex gap-1">
          {(["csv", "xlsx", "pdf"] as const).map((fmt) => (
            <button
              key={fmt}
              className="btn-ghost !px-2.5 !py-1.5 text-xs uppercase"
              disabled={exporting === `all:${fmt}`}
              onClick={() => doExport(() => api.exportAdminAllUsers(fmt), `all:${fmt}`)}
            >
              {exporting === `all:${fmt}` ? "…" : `Export All ${fmt}`}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800/70">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key as "clients" | "shoppers")}
            className={
              "rounded-lg px-3.5 py-2 text-sm font-semibold transition " +
              (tab === t.key
                ? "bg-brand-600 text-white shadow"
                : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100")
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "clients" ? (
        <ClientUsersTable exporting={exporting} onExport={doExport} />
      ) : (
        <ShopperUsersTable exporting={exporting} onExport={doExport} />
      )}
    </div>
  );
}

function ExportRow({
  scope,
  exporting,
  onExport,
  fns,
}: {
  scope: string;
  exporting: string | null;
  onExport: (fn: () => Promise<void>, key: string) => void;
  fns: Record<"csv" | "xlsx" | "pdf", () => Promise<void>>;
}) {
  return (
    <div className="flex gap-1">
      {(["csv", "xlsx", "pdf"] as const).map((fmt) => {
        const key = `${scope}:${fmt}`;
        return (
          <button
            key={fmt}
            className="btn-ghost !px-2 !py-1 text-xs uppercase"
            disabled={exporting === key}
            onClick={() => onExport(fns[fmt], key)}
          >
            {exporting === key ? "…" : fmt}
          </button>
        );
      })}
    </div>
  );
}

function ClientUsersTable({
  exporting,
  onExport,
}: {
  exporting: string | null;
  onExport: (fn: () => Promise<void>, key: string) => void;
}) {
  const { data, loading, error, reload } = useApi(() => api.adminClientUsers());
  const [showCreate, setShowCreate] = useState(false);
  if (loading && !data) return <Loading label="Loading client users…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <div className="card overflow-x-auto">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 p-3 dark:border-slate-800">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          {data.total} client user{data.total === 1 ? "" : "s"}
        </span>
        <div className="flex items-center gap-2">
          <button className="btn-primary h-8 !px-3 text-xs" onClick={() => setShowCreate(true)}>
            + New Client
          </button>
          <ExportRow
            scope="clients"
            exporting={exporting}
            onExport={onExport}
            fns={{
              csv: () => api.exportAdminClientUsers("csv"),
              xlsx: () => api.exportAdminClientUsers("xlsx"),
              pdf: () => api.exportAdminClientUsers("pdf"),
            }}
          />
        </div>
      </div>
      {showCreate && (
        <NewClientModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            reload();
          }}
        />
      )}
      <table className="min-w-full">
        <thead className="border-b border-slate-100 dark:border-slate-800">
          <tr>
            <th className="th">Company</th>
            <th className="th">Email</th>
            <th className="th">Status</th>
            <th className="th">Last Login</th>
            <th className="th text-center">Campaigns</th>
            <th className="th text-center">Outreach Activity</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
          {data.items.map((u: any) => (
            <tr key={u.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
              <td className="td font-medium text-slate-800 dark:text-slate-100">{u.company || "—"}</td>
              <td className="td text-slate-500">{u.email}</td>
              <td className="td">
                <Badge className={statusBadgeClass(u.status === "active" ? "accepted" : "created")}>{u.status}</Badge>
              </td>
              <td className="td text-slate-500">{u.last_login ? fmtDateTime(u.last_login) : "Never"}</td>
              <td className="td text-center">{u.campaign_count}</td>
              <td className="td text-center">{u.outreach_activity}</td>
            </tr>
          ))}
          {data.items.length === 0 && (
            <tr>
              <td colSpan={6} className="td py-10 text-center text-slate-400">
                <EmptyState title="No client users yet" />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ShopperUsersTable({
  exporting,
  onExport,
}: {
  exporting: string | null;
  onExport: (fn: () => Promise<void>, key: string) => void;
}) {
  const { data, loading, error, reload } = useApi(() => api.adminShopperUsers());
  if (loading && !data) return <Loading label="Loading shoppers…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <div className="card overflow-x-auto">
      <div className="flex items-center justify-between border-b border-slate-100 p-3 dark:border-slate-800">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          {data.total} shopper{data.total === 1 ? "" : "s"}
        </span>
        <ExportRow
          scope="shoppers"
          exporting={exporting}
          onExport={onExport}
          fns={{
            csv: () => api.exportAdminShopperUsers("csv"),
            xlsx: () => api.exportAdminShopperUsers("xlsx"),
            pdf: () => api.exportAdminShopperUsers("pdf"),
          }}
        />
      </div>
      <table className="min-w-full">
        <thead className="border-b border-slate-100 dark:border-slate-800">
          <tr>
            <th className="th">Shopper</th>
            <th className="th hidden md:table-cell">Location</th>
            <th className="th">Status</th>
            <th className="th text-center">Invited</th>
            <th className="th text-center">Assignments</th>
            <th className="th text-center">Accepts</th>
            <th className="th text-center">Declines</th>
            <th className="th">Last Activity</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
          {data.items.map((s: any) => (
            <tr key={s.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
              <td className="td font-medium text-slate-800 dark:text-slate-100">{s.name}</td>
              <td className="td hidden text-slate-500 md:table-cell">{s.location || "—"}</td>
              <td className="td">
                <Badge className={statusBadgeClass(s.status === "available" ? "accepted" : "created")}>{s.status}</Badge>
              </td>
              <td className="td text-center">{s.campaigns_invited}</td>
              <td className="td text-center">{s.assignments}</td>
              <td className="td text-center">{s.accepts}</td>
              <td className="td text-center">{s.declines}</td>
              <td className="td text-slate-500">{s.last_activity ? fmtDateTime(s.last_activity) : "—"}</td>
            </tr>
          ))}
          {data.items.length === 0 && (
            <tr>
              <td colSpan={8} className="td py-10 text-center text-slate-400">
                <EmptyState title="No shoppers yet" />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function NewClientModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const [companyName, setCompanyName] = useState("");
  const [contactName, setContactName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState(() => Math.random().toString(36).slice(2, 10) + "A1!");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null);

  async function create() {
    if (!companyName.trim() || !contactName.trim() || !email.trim() || password.length < 8) {
      toast("Fill in all fields — password needs at least 8 characters.", "error");
      return;
    }
    setCreating(true);
    try {
      await api.adminCreateClient({
        company_name: companyName.trim(),
        contact_name: contactName.trim(),
        email: email.trim(),
        password,
      });
      setCreated({ email: email.trim(), password });
      toast(`Client login created for ${companyName.trim()}.`, "success");
    } catch (e: any) {
      toast(e?.message || "Failed to create client", "error");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full max-w-md rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        {!created ? (
          <>
            <h3 className="text-base font-bold text-slate-900 dark:text-white">New Client Login</h3>
            <p className="mt-1 text-xs text-slate-400">
              The client can change this password themselves from their Profile page after logging in.
            </p>
            <div className="mt-4 space-y-3">
              <div>
                <label className="label">Company name</label>
                <input className="input" value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
              </div>
              <div>
                <label className="label">Contact name</label>
                <input className="input" value={contactName} onChange={(e) => setContactName(e.target.value)} />
              </div>
              <div>
                <label className="label">Login email</label>
                <input
                  type="email"
                  className="input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div>
                <label className="label">Initial password</label>
                <input className="input font-mono" value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button className="btn-secondary" onClick={onClose}>Cancel</button>
              <button className="btn-primary" onClick={create} disabled={creating}>
                {creating ? <Spinner /> : null} Create Login
              </button>
            </div>
          </>
        ) : (
          <>
            <h3 className="text-base font-bold text-slate-900 dark:text-white">Client login created</h3>
            <p className="mt-1 text-xs text-slate-400">
              Share these credentials with the client — this password won't be shown again.
            </p>
            <div className="mt-4 space-y-3 rounded-lg bg-slate-50 p-4 text-sm dark:bg-slate-800/50">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Email</div>
                <div className="font-mono text-slate-800 dark:text-slate-100">{created.email}</div>
              </div>
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Password</div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-slate-800 dark:text-slate-100">{created.password}</span>
                  <CopyButton value={created.password} label="" />
                </div>
              </div>
            </div>
            <div className="mt-5 flex justify-end">
              <button className="btn-primary" onClick={onCreated}>Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
