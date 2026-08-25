import { AttributionCard } from "./Attribution";
import { IconX } from "./Icons";
import { Timeline } from "./Timeline";
import { Badge, CopyButton, Loading } from "./ui";
import { api } from "../lib/api";
import { fmtDateTime, fmtDuration, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";

export function InvitationDrawer({
  invitationId,
  onClose,
}: {
  invitationId: string;
  onClose: () => void;
}) {
  const { data, loading } = useApi(() => api.invitation(invitationId), [invitationId]);
  // preview=true so viewing this in the drawer never counts as a real
  // shopper open — same real subject/body/links the shopper actually got,
  // rendered as an email rather than a raw-link list (spec: show the client
  // what was actually sent, for every invitation in the history).
  const emailPreview = useApi(() => api.previewEmail(invitationId, true), [invitationId]);

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <aside className="absolute inset-y-0 right-0 flex w-full max-w-lg flex-col bg-white shadow-2xl dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              Invitation
            </div>
            <div className="text-lg font-bold text-slate-900 dark:text-white">
              {data?.reference || "…"}
            </div>
          </div>
          <button className="btn-ghost" onClick={onClose} aria-label="Close">
            <IconX />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {loading && !data ? (
            <Loading />
          ) : !data ? (
            <div className="text-sm text-slate-400">Not found.</div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={statusBadgeClass(data.status)}>{data.status}</Badge>
                <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                  {data.shopper_name}
                </span>
                <span className="text-sm text-slate-400">{data.shopper_email}</span>
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <Field label="Client" value={data.client_name} />
                <Field label="Campaign" value={data.campaign_name} />
                <Field label="Shop" value={data.shop_name} />
                <Field label="Sent" value={fmtDateTime(data.sent_at)} />
                <Field label="Delivered" value={fmtDateTime(data.delivered_at)} />
                <Field label="Opened" value={fmtDateTime(data.opened_at)} />
                <Field label="Clicked" value={fmtDateTime(data.clicked_at)} />
                <Field label="Visited" value={fmtDateTime(data.visited_at)} />
              </div>

              {(fmtDuration(data.sent_at, data.clicked_at) || fmtDuration(data.clicked_at, data.responded_at)) && (
                <div className="grid grid-cols-2 gap-3">
                  {fmtDuration(data.sent_at, data.clicked_at) && (
                    <div className="rounded-lg bg-slate-50 p-3 text-center dark:bg-slate-800/50">
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                        Email Sent → Click
                      </div>
                      <div className="mt-1 font-bold text-slate-800 dark:text-slate-100">
                        {fmtDuration(data.sent_at, data.clicked_at)}
                      </div>
                    </div>
                  )}
                  {fmtDuration(data.clicked_at, data.responded_at) && (
                    <div className="rounded-lg bg-slate-50 p-3 text-center dark:bg-slate-800/50">
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                        Click → {data.response === "declined" ? "Decline" : "Accept"}
                      </div>
                      <div className="mt-1 font-bold text-slate-800 dark:text-slate-100">
                        {fmtDuration(data.clicked_at, data.responded_at)}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {data.email_delivery && (
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-800 dark:bg-slate-800/50">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">ShopperMatch email outbox</div>
                  <div className="mt-1 font-medium capitalize text-slate-800 dark:text-slate-100">
                    {data.email_delivery.status} via {data.email_delivery.provider} · attempt {data.email_delivery.attempts}
                  </div>
                  {data.email_delivery.last_error && <div className="mt-1 text-xs text-rose-600 dark:text-rose-300">{data.email_delivery.last_error}</div>}
                </div>
              )}

              <AttributionCard attribution={data.attribution} />

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Email Preview
                  </div>
                  {emailPreview.data?.subject && (
                    <CopyButton value={data.urls.tracking_url} label="Copy tracking link" />
                  )}
                </div>
                {emailPreview.data?.subject && (
                  <div className="truncate rounded-t-lg border border-b-0 border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-800 dark:bg-slate-800/50">
                    <span className="text-slate-400">Subject: </span>
                    <span className="font-medium text-slate-700 dark:text-slate-200">{emailPreview.data.subject}</span>
                  </div>
                )}
                {emailPreview.loading && !emailPreview.data ? (
                  <div className="rounded-lg border border-slate-200 p-6 text-center text-sm text-slate-400 dark:border-slate-800">
                    Rendering the email as it was sent…
                  </div>
                ) : emailPreview.data?.html ? (
                  <iframe
                    title="Email preview"
                    // This is a read-only preview, not a live email — the
                    // sandbox already blocks scripts/forms, but a plain link
                    // click still navigates the iframe's own frame away from
                    // the preview. Disabling pointer-events on links (via a
                    // trailing <style>, which works even with scripts
                    // sandboxed) keeps clicking "View Assignment" etc. inert.
                    srcDoc={emailPreview.data.html + "<style>a{pointer-events:none!important;cursor:default!important;}</style>"}
                    sandbox=""
                    className={
                      "h-[420px] w-full border border-slate-200 bg-white dark:border-slate-800" +
                      (emailPreview.data.subject ? " rounded-b-lg" : " rounded-lg")
                    }
                  />
                ) : (
                  <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-sm text-slate-400 dark:border-slate-800">
                    No preview available for this invitation.
                  </div>
                )}
              </div>

              <div>
                <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Event timeline
                </div>
                <Timeline events={data.events} />
              </div>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-slate-800 dark:text-slate-200">{value || "—"}</div>
    </div>
  );
}
