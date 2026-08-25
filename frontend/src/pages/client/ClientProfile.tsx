import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Avatar, Badge, Loading, Spinner, useToast } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useApi } from "../../lib/useApi";
import { ErrorBox } from "../Dashboard";

export function ClientProfile() {
  const { data, loading, error, reload } = useApi(() => api.clientProfile());
  if (loading && !data) return <Loading label="Loading profile…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <div className="max-w-lg space-y-5">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Profile</h1>

      <div className="card flex items-center gap-4 p-6">
        <Avatar name={data.user_name} className="h-14 w-14 text-base" />
        <div>
          <div className="text-lg font-semibold text-slate-900 dark:text-white">{data.user_name}</div>
          <div className="text-sm text-slate-500 dark:text-slate-400">{data.user_email}</div>
        </div>
      </div>

      <div className="card p-6">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Organization</div>
        <div className="mt-2 flex items-center gap-2">
          <span className="text-lg font-semibold text-slate-900 dark:text-white">{data.client_name}</span>
          <Badge className="bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
            {data.client_status}
          </Badge>
        </div>
      </div>

      <ChangePasswordCard />
      <DangerZoneCard />

      <p className="text-xs text-slate-400">
        Need to update your company name or add a teammate? Contact your ISN account manager.
      </p>
    </div>
  );
}

function ChangePasswordCard() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    if (next.length < 8) {
      toast("New password must be at least 8 characters.", "error");
      return;
    }
    if (next !== confirm) {
      toast("New password and confirmation don't match.", "error");
      return;
    }
    setSaving(true);
    try {
      await api.changePassword(current, next);
      toast("Password updated.", "success");
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (e: any) {
      toast(e?.message || "Failed to change password", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card p-6">
      <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Change Password</h2>
      <div className="mt-4 space-y-3">
        <div>
          <label className="label">Current password</label>
          <input
            type="password"
            className="input"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
          />
        </div>
        <div>
          <label className="label">New password</label>
          <input
            type="password"
            className="input"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
          />
        </div>
        <div>
          <label className="label">Confirm new password</label>
          <input
            type="password"
            className="input"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
        </div>
        <button
          className="btn-primary"
          onClick={submit}
          disabled={saving || !current || !next || !confirm}
        >
          {saving ? <Spinner /> : null} Update Password
        </button>
      </div>
    </div>
  );
}

function DangerZoneCard() {
  const toast = useToast();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [action, setAction] = useState<"deactivate" | "delete" | null>(null);
  const [password, setPassword] = useState("");
  const [running, setRunning] = useState(false);

  function openModal(a: "deactivate" | "delete") {
    setAction(a);
    setPassword("");
  }

  async function confirmAction() {
    if (!password) {
      toast("Enter your password to confirm.", "error");
      return;
    }
    setRunning(true);
    try {
      if (action === "deactivate") {
        await api.clientDeactivateAccount(password);
        toast("Account deactivated.", "success");
      } else {
        await api.clientDeleteAccount(password);
        toast("Account deleted.", "success");
      }
      logout();
      navigate("/login", { replace: true });
    } catch (e: any) {
      toast(e?.message || "Action failed", "error");
    } finally {
      setRunning(false);
      setAction(null);
    }
  }

  return (
    <div className="card border-rose-200 p-6 dark:border-rose-900">
      <h2 className="text-sm font-semibold text-rose-600 dark:text-rose-400">Danger Zone</h2>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        Your campaign history stays with ISN either way — these actions only affect your ability to log in.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button className="btn-secondary" onClick={() => openModal("deactivate")}>
          Deactivate Account
        </button>
        <button
          className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-600 transition hover:bg-rose-50 dark:border-rose-800 dark:text-rose-400 dark:hover:bg-rose-950/40"
          onClick={() => openModal("delete")}
        >
          Delete Account
        </button>
      </div>

      {action && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={() => setAction(null)} />
          <div className="relative w-full max-w-md rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
            <h3 className="text-base font-bold text-slate-900 dark:text-white">
              {action === "deactivate" ? "Deactivate your account?" : "Delete your account?"}
            </h3>
            <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
              {action === "deactivate"
                ? "You'll be signed out immediately and won't be able to log back in until ISN reactivates your account."
                : "This permanently removes your login. You'll be signed out immediately and this can't be undone from your side — contact ISN if you need access restored."}
            </p>
            <div className="mt-4">
              <label className="label">Confirm your password</label>
              <input
                type="password"
                className="input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
              />
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button className="btn-secondary" onClick={() => setAction(null)}>
                Cancel
              </button>
              <button
                className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-rose-700 disabled:opacity-50"
                onClick={confirmAction}
                disabled={running}
              >
                {running ? <Spinner /> : null} {action === "deactivate" ? "Deactivate" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
