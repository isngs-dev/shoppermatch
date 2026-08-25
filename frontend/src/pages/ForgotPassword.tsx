import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Logo, Spinner } from "../components/ui";
import { api } from "../lib/api";

export function ForgotPassword() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.forgotPassword(email.trim());
      setSent(true);
    } catch (err: any) {
      setError(err?.message || "Something went wrong");
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
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Forgot password</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Enter your account email and we'll send a reset link.
          </p>

          {sent ? (
            <div className="mt-6 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
              If an account with that email exists, a password reset link has been sent. Check your inbox — the
              link expires in 30 minutes.
            </div>
          ) : (
            <form onSubmit={submit} className="mt-6 space-y-4">
              <div>
                <label className="label">Email</label>
                <input
                  className="input"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="username"
                  autoFocus
                  required
                />
              </div>

              {error && (
                <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
                  {error}
                </div>
              )}

              <button className="btn-primary w-full py-2.5" disabled={busy}>
                {busy ? <Spinner /> : "Send reset link"}
              </button>
            </form>
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
