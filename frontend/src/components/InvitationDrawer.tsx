import { AttributionCard } from "./Attribution";
import { IconX } from "./Icons";
import { Timeline } from "./Timeline";
import { Badge, CopyButton, Loading } from "./ui";
import { api } from "../lib/api";
import { fmtDateTime, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";

export function InvitationDrawer({
  invitationId,
  onClose,
}: {
  invitationId: string;
  onClose: () => void;
}) {
  const { data, loading } = useApi(() => api.invitation(invitationId), [invitationId]);

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
                <Field label="Campaign" value={data.campaign_name} />
                <Field label="Shop" value={data.shop_name} />
                <Field label="Sent" value={fmtDateTime(data.sent_at)} />
                <Field label="Delivered" value={fmtDateTime(data.delivered_at)} />
                <Field label="Opened" value={fmtDateTime(data.opened_at)} />
                <Field label="Clicked" value={fmtDateTime(data.clicked_at)} />
              </div>

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
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Tracked URLs
                </div>
                <UrlRow label="Tracking (click)" value={data.urls.tracking_url} />
                <UrlRow label="Shopper landing" value={data.urls.shopper_url} />
                <UrlRow label="Open pixel" value={data.urls.pixel_url} />
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

function UrlRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-800/50">
        <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
        <div className="truncate font-mono text-xs text-slate-600 dark:text-slate-300">{value}</div>
      </div>
      <CopyButton value={value} label="" />
    </div>
  );
}
