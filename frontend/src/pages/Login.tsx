import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { IconArrowRight } from "../components/Icons";
import { Logo, Spinner } from "../components/ui";
import { useAuth } from "../lib/auth";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as any)?.from as string | undefined;

  const [email, setEmail] = useState("admin@isn.com");
  const [password, setPassword] = useState("isn-demo-2026");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await login(email, password);
      const home = user.role === "admin" ? "/admin/dashboard" : "/client/dashboard";
      // Only honor a "from" redirect if it actually belongs to this role's
      // portal — otherwise a client bounced off /admin/* would land right
      // back on the page they're not allowed to see.
      const target = from && from.startsWith(`/${user.role === "admin" ? "admin" : "client"}/`) ? from : home;
      navigate(target, { replace: true });
    } catch (err: any) {
      setError(err?.message || "Login failed");
    } finally {
      setBusy(false);
    }
  }

  function fillDemo(kind: "admin" | "client") {
    if (kind === "admin") {
      setEmail("admin@isn.com");
      setPassword("isn-demo-2026");
    } else {
      setEmail("client@nike-demo.example");
      setPassword("client-demo-2026");
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 dark:bg-slate-950">
      <div className="w-full max-w-md">
        <div className="mb-6 flex justify-center">
          <Logo />
        </div>
        <div className="card p-8">
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Sign in</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            ISN operators land in the Admin Portal; brand logins land in the Client Portal.
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
              <div className="flex items-center justify-between">
                <label className="label">Password</label>
                <button
                  type="button"
                  className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-400"
                  onClick={() => navigate("/forgot-password")}
                >
                  Forgot password?
                </button>
              </div>
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

          <div className="mt-5 space-y-2 rounded-lg bg-slate-50 px-3 py-2.5 text-xs text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
            <div className="font-semibold text-slate-600 dark:text-slate-300">Demo credentials</div>
            <button type="button" className="flex w-full items-center justify-between rounded-md px-1.5 py-1 text-left hover:bg-white dark:hover:bg-slate-900" onClick={() => fillDemo("admin")}>
              <span>ISN Admin — admin@isn.com / isn-demo-2026</span>
              <span className="text-brand-600">Use</span>
            </button>
            <button type="button" className="flex w-full items-center justify-between rounded-md px-1.5 py-1 text-left hover:bg-white dark:hover:bg-slate-900" onClick={() => fillDemo("client")}>
              <span>Nike Client — client@nike-demo.example / client-demo-2026</span>
              <span className="text-brand-600">Use</span>
            </button>
          </div>
        </div>
        <div className="mt-4 flex flex-col items-center gap-2 text-center text-sm">
          <span className="text-slate-500 dark:text-slate-400">
            New brand?{" "}
            <button className="font-semibold text-brand-600 hover:underline dark:text-brand-400" onClick={() => navigate("/signup")}>
              Create a client account
            </button>
          </span>
          <button className="text-slate-500 hover:text-brand-600" onClick={() => navigate("/")}>
            ← Back to home
          </button>
        </div>
      </div>
    </div>
  );
}
