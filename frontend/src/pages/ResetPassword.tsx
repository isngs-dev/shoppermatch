import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Logo, Spinner } from "../components/ui";
import { api } from "../lib/api";

export function ResetPassword() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") || "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.resetPassword(token, password);
      setDone(true);
    } catch (err: any) {
      setError(err?.message || "This reset link is invalid or has expired.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 dark:bg-slate-950">
      <div className="w-full max-w-md">
        <div className="mb-6 flex justify-center">
          <Logo />
        </div>
        <div className="card p-8">
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Reset password</h1>

          {!token ? (
            <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
              This link is missing its reset token. Request a new one from the Forgot Password page.
            </div>
          ) : done ? (
            <>
              <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
                Your password has been updated.
              </div>
              <button className="btn-primary mt-4 w-full py-2.5" onClick={() => navigate("/login")}>
                Go to sign in
              </button>
            </>
          ) : (
            <>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Choose a new password.</p>
              <form onSubmit={submit} className="mt-6 space-y-4">
                <div>
                  <label className="label">New password</label>
                  <input
                    className="input"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="new-password"
                    minLength={8}
                    autoFocus
                    required
                  />
                  <p className="mt-1 text-[11px] text-slate-400">At least 8 characters.</p>
                </div>
                <div>
                  <label className="label">Confirm new password</label>
                  <input
                    className="input"
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    autoComplete="new-password"
                    minLength={8}
                    required
                  />
                </div>

                {error && (
                  <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
                    {error}
                  </div>
                )}

                <button className="btn-primary w-full py-2.5" disabled={busy}>
                  {busy ? <Spinner /> : "Update password"}
                </button>
              </form>
            </>
          )}
        </div>
        <div className="mt-4 text-center">
          <button className="text-sm text-slate-500 hover:text-brand-600" onClick={() => navigate("/login")}>
            ← Back to sign in
          </button>
        </div>
      </div>
    </div>
  );
}
