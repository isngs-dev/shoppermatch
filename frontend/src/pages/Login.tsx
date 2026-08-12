import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { IconArrowRight } from "../components/Icons";
import { Logo, Spinner } from "../components/ui";
import { useAuth } from "../lib/auth";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as any)?.from || "/dashboard";

  const [email, setEmail] = useState("admin@isn.com");
  const [password, setPassword] = useState("isn-demo-2026");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err: any) {
      setError(err?.message || "Login failed");
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
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">ISN Admin sign in</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Access the shopper outreach & attribution dashboard.
          </p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            <div>
              <label className="label">Email</label>
              <input
                className="input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                required
              />
            </div>
            <div>
              <label className="label">Password</label>
              <input
                className="input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>

            {error && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
                {error}
              </div>
            )}

            <button className="btn-primary w-full py-2.5" disabled={busy}>
              {busy ? <Spinner /> : <>Sign in <IconArrowRight width={16} height={16} /></>}
            </button>
          </form>

          <div className="mt-5 rounded-lg bg-slate-50 px-3 py-2.5 text-xs text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
            <span className="font-semibold text-slate-600 dark:text-slate-300">Demo credentials</span>
            <br />
            admin@isn.com &nbsp;/&nbsp; isn-demo-2026
          </div>
        </div>
        <div className="mt-4 text-center">
          <button className="text-sm text-slate-500 hover:text-brand-600" onClick={() => navigate("/")}>
            ← Back to home
          </button>
        </div>
      </div>
    </div>
  );
}
