import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { IconArrowRight } from "../components/Icons";
import { Logo, Spinner } from "../components/ui";
import { useAuth } from "../lib/auth";

export function SignUp() {
  const { register } = useAuth();
  const navigate = useNavigate();

  const [companyName, setCompanyName] = useState("");
  const [contactName, setContactName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      await register({
        company_name: companyName.trim(),
        contact_name: contactName.trim(),
        email: email.trim(),
        password,
      });
      navigate("/client/dashboard", { replace: true });
    } catch (err: any) {
      setError(err?.message || "Failed to create account");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10 dark:bg-slate-950">
      <div className="w-full max-w-md">
        <div className="mb-6 flex justify-center">
          <Logo />
        </div>
        <div className="card p-8">
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Create your client account</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Set up your brand's Client Portal login — ISN will attach your campaigns once your account is ready.
          </p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            <div>
              <label className="label">Company name</label>
              <input
                className="input"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder="Acme Retail Co."
                required
              />
            </div>
            <div>
              <label className="label">Your name</label>
              <input
                className="input"
                value={contactName}
                onChange={(e) => setContactName(e.target.value)}
                placeholder="Jordan Lee"
                required
              />
            </div>
            <div>
              <label className="label">Work email</label>
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
                autoComplete="new-password"
                minLength={8}
                required
              />
              <p className="mt-1 text-[11px] text-slate-400">At least 8 characters.</p>
            </div>
            <div>
              <label className="label">Confirm password</label>
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
              {busy ? <Spinner /> : <>Create account <IconArrowRight width={16} height={16} /></>}
            </button>
          </form>
        </div>
        <div className="mt-4 flex justify-center gap-4 text-sm">
          <button className="text-slate-500 hover:text-brand-600" onClick={() => navigate("/login")}>
            Already have an account? Sign in
          </button>
        </div>
      </div>
    </div>
  );
}
