import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { IconArrowRight, IconExternal, IconMoon, IconSun, IconTarget } from "../components/Icons";
import { Logo } from "../components/ui";
import { api } from "../lib/api";
import { useTheme } from "../lib/theme";

const FLOW = [
  "SASSIE",
  "ShopperMatch.AI",
  "AI Recommendation",
  "ISN Outreach",
  "Tracking",
  "Shopper Response",
];

const FEATURES = [
  {
    title: "Unique UUID attribution",
    body: "Every invitation gets an unguessable tracking token that maps to exactly one shopper — no raw database ids in public URLs.",
  },
  {
    title: "Pixel + click tracking",
    body: "A 1×1 GIF signals email opens (no JavaScript), while the /r redirect reliably captures clicks before landing the shopper.",
  },
  {
    title: "Real-time outreach funnel",
    body: "Sent → Delivered → Opened → Clicked → Accepted, with per-shopper event timelines and an ISN-attributed badge.",
  },
];

export function Home() {
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const [sampleToken, setSampleToken] = useState<string | null>(null);

  useEffect(() => {
    api.sampleInvitation().then((r) => setSampleToken(r.tracking_token)).catch(() => {});
  }, []);

  return (
    <div className="min-h-screen bg-white dark:bg-slate-950">
      {/* Nav */}
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <Logo />
        <div className="flex items-center gap-2">
          <button className="btn-ghost" onClick={toggle} aria-label="Toggle theme">
            {theme === "dark" ? <IconSun /> : <IconMoon />}
          </button>
          <button className="btn-secondary" onClick={() => navigate("/login")}>
            Sign in
          </button>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-6 pb-8 pt-10 sm:pt-20">
        <div className="mx-auto max-w-3xl text-center">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
            <IconTarget width={14} height={14} className="text-brand-500" />
            Intelligent Shopper Outreach & Attribution Platform
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight text-slate-900 dark:text-white sm:text-6xl">
            Fill every shop faster.
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg text-slate-600 dark:text-slate-300">
            AI-powered shopper matching and intelligent outreach for mystery shopping operations —
            with end-to-end attribution from the ISN invitation to the shopper's response.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <button className="btn-primary px-6 py-3 text-base" onClick={() => navigate("/login")}>
              Sign in
              <IconArrowRight width={18} height={18} />
            </button>
            <button
              className="btn-secondary px-6 py-3 text-base"
              disabled={!sampleToken}
              onClick={() => sampleToken && navigate(`/shop/${sampleToken}`)}
            >
              View Shopper Invitation
              <IconExternal width={16} height={16} />
            </button>
          </div>
          <p className="mt-3 text-xs text-slate-400">
            Demo login is pre-filled on the sign-in screen.
          </p>
        </div>
      </section>

      {/* Architecture flow */}
      <section className="mx-auto max-w-6xl px-6 py-10">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-6 dark:border-slate-800 dark:bg-slate-900/50">
          <div className="mb-5 text-center text-xs font-semibold uppercase tracking-wider text-slate-400">
            How attribution flows
          </div>
          <div className="flex flex-wrap items-center justify-center gap-2">
            {FLOW.map((step, i) => (
              <div key={step} className="flex items-center gap-2">
                <div
                  className={
                    "rounded-lg border px-3 py-2 text-sm font-semibold " +
                    (step === "ShopperMatch.AI"
                      ? "border-brand-300 bg-brand-600 text-white dark:border-brand-700"
                      : "border-slate-200 bg-white text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200")
                  }
                >
                  {step}
                </div>
                {i < FLOW.length - 1 && (
                  <IconArrowRight width={16} height={16} className="text-slate-300 dark:text-slate-600" />
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-6xl px-6 pb-20">
        <div className="grid gap-5 sm:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="card p-6">
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">{f.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
                {f.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      <footer className="border-t border-slate-200 py-8 text-center text-xs text-slate-400 dark:border-slate-800">
        ShopperMatch.AI — synthetic demo data only. Built to demonstrate ISN outreach attribution.
      </footer>
    </div>
  );
}
