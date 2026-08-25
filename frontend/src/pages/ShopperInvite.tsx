import { useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import {
  IconCheck,
  IconClock,
  IconLocation,
  IconShield,
  IconWallet,
  IconX,
} from "../components/Icons";
import { Logo, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { fmtDate } from "../lib/format";
import { useApi } from "../lib/useApi";

export function ShopperInvite() {
  const { token = "" } = useParams();
  const { data, loading, error, reload } = useApi(() => api.publicInvitation(token), [token]);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [showInfo, setShowInfo] = useState(false);
  const [localResponse, setLocalResponse] = useState<string | null>(null);
  const [note, setNote] = useState("");

  async function respond(response: "accepted" | "declined") {
    setSubmitting(response);
    try {
      const res = await api.respond(token, response, note.trim() || undefined);
      setLocalResponse(res.response || response);
      reload();
    } catch {
      setLocalResponse(null);
    } finally {
      setSubmitting(null);
    }
  }

  if (loading && !data) {
    return (
      <CenteredShell>
        <Spinner className="text-brand-500" />
      </CenteredShell>
    );
  }

  if (error || !data) {
    return (
      <CenteredShell>
        <div className="card max-w-md p-8 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-rose-50 text-rose-500 dark:bg-rose-950">
            <IconX />
          </div>
          <h1 className="text-lg font-bold text-slate-900 dark:text-white">Invitation not found</h1>
          <p className="mt-1 text-sm text-slate-500">
            This invitation link is invalid or has expired.
          </p>
        </div>
      </CenteredShell>
    );
  }

  const responded = data.response || localResponse;
  const comp = data.shop.compensation;
  const symbol = data.shop.currency === "INR" ? "₹" : "";

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900">
      <header className="mx-auto flex max-w-2xl items-center justify-between px-6 py-5">
        <Logo />
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-500 shadow-sm dark:bg-slate-800 dark:text-slate-300">
          <IconShield width={13} height={13} className="text-emerald-500" />
          Delivered through ISN
        </span>
      </header>

      <main className="mx-auto max-w-2xl px-6 pb-16">
        <div className="card overflow-hidden">
          <div className="bg-slate-900 px-7 py-6 text-white">
            <div className="text-xs font-semibold uppercase tracking-wider text-brand-300">
              Mystery Shopping Invitation
            </div>
            <h1 className="mt-1 text-2xl font-bold">
              Hi {data.shopper_first_name}, you're invited 🎯
            </h1>
            <p className="mt-1 text-sm text-slate-300">
              {data.campaign.client_name} · {data.campaign.name}
            </p>
          </div>

          <div className="p-7">
            <div className="grid gap-4 sm:grid-cols-2">
              <InfoTile icon={<IconLocation width={18} />} label="Location" value={`${data.shop.city || ""}${data.shop.state ? ", " + data.shop.state : ""}`} sub={data.shop.shop_name} />
              <InfoTile icon={<IconWallet width={18} />} label="Compensation" value={`${symbol}${(comp || 0).toLocaleString()}`} accent />
              <InfoTile icon={<IconClock width={18} />} label="Visit Window" value={`${fmtDate(data.shop.visit_start)} – ${fmtDate(data.shop.visit_end)}`} />
              <InfoTile icon={<IconClock width={18} />} label="Deadline" value={fmtDate(data.campaign.deadline)} />
            </div>

            {/* Response area */}
            {responded ? (
              <div
                className={
                  "mt-7 flex items-center gap-3 rounded-xl border p-4 " +
                  (responded === "accepted"
                    ? "border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40"
                    : "border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40")
                }
              >
                <div
                  className={
                    "flex h-10 w-10 items-center justify-center rounded-full " +
                    (responded === "accepted"
                      ? "bg-emerald-500 text-white"
                      : "bg-rose-500 text-white")
                  }
                >
                  {responded === "accepted" ? <IconCheck /> : <IconX />}
                </div>
                <div>
                  <div className="font-semibold text-slate-900 dark:text-white">
                    {responded === "accepted" ? "Assignment accepted" : "Assignment declined"}
                  </div>
                  <div className="text-sm text-slate-500 dark:text-slate-400">
                    {responded === "accepted"
                      ? "Thanks! The ISN team has been notified and will follow up with next steps."
                      : "No problem — we've let the ISN team know."}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-7 space-y-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
                    Any comments? (optional)
                  </label>
                  <textarea
                    className="input h-16 resize-none text-sm"
                    placeholder="e.g. Great timing, or let us know why this isn't a fit right now…"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-3 sm:flex-row">
                  <button
                    className="btn-primary flex-1 py-3 text-base"
                    disabled={!!submitting}
                    onClick={() => respond("accepted")}
                  >
                    {submitting === "accepted" ? <Spinner /> : <><IconCheck width={18} height={18} /> Accept Assignment</>}
                  </button>
                  <button
                    className="btn-secondary flex-1 py-3 text-base"
                    disabled={!!submitting}
                    onClick={() => respond("declined")}
                  >
                    {submitting === "declined" ? <Spinner /> : <>Decline</>}
                  </button>
                </div>
                <button
                  className="btn-ghost w-full"
                  onClick={() => setShowInfo((v) => !v)}
                >
                  Request More Information
                </button>
                {showInfo && (
                  <div className="rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:bg-slate-800/50 dark:text-slate-300">
                    You can visit the store anytime during the visit window above. You'll evaluate
                    service, product availability and store presentation, then submit a short report.
                    Compensation is paid on approval. Reply to the ISN email for anything specific.
                  </div>
                )}
              </div>
            )}

            {/* Attribution footer */}
            <div className="mt-7 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-4 text-xs text-slate-400 dark:border-slate-800">
              <span>
                Invitation ID: <span className="font-semibold text-slate-500 dark:text-slate-300">{data.reference}</span>
                <span className="mx-2">·</span>
                Token: <span className="font-mono">{data.tracking_token_masked}</span>
              </span>
              <span className="inline-flex items-center gap-1.5 font-semibold text-emerald-600 dark:text-emerald-400">
                <IconShield width={13} height={13} /> Invitation delivered through ISN
              </span>
            </div>
          </div>
        </div>

        <p className="mt-4 text-center text-xs text-slate-400">
          ShopperMatch.AI · This is a synthetic demo invitation.
        </p>
      </main>
    </div>
  );
}

function InfoTile({
  icon,
  label,
  value,
  sub,
  accent,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
      <div className="flex items-center gap-2 text-slate-400">
        {icon}
        <span className="text-[11px] font-semibold uppercase tracking-wide">{label}</span>
      </div>
      <div
        className={
          "mt-1 text-lg font-bold " +
          (accent ? "text-emerald-600 dark:text-emerald-400" : "text-slate-900 dark:text-white")
        }
      >
        {value}
      </div>
      {sub && <div className="text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

function CenteredShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 dark:bg-slate-950">
      {children}
    </div>
  );
}
