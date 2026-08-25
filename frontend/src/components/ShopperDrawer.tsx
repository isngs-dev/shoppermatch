import { IconHistory, IconX } from "./Icons";
import { Avatar, Badge, Loading } from "./ui";
import { api } from "../lib/api";
import { fmtDate, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";

const STATUS_KEY: Record<string, string> = {
  Completed: "accepted",
  Accepted: "accepted",
  Declined: "declined",
  Clicked: "clicked",
  Opened: "opened",
  Sent: "sent",
  Pending: "created",
};

export function ShopperDrawer({ shopperId, onClose }: { shopperId: string; onClose: () => void }) {
  const shopper = useApi(() => api.shopper(shopperId), [shopperId]);
  const history = useApi(() => api.shopperCampaignHistory(shopperId), [shopperId]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-md flex-col overflow-hidden bg-white shadow-2xl dark:bg-slate-900 sm:max-w-lg">
        <div className="flex items-center justify-between border-b border-slate-200 p-4 dark:border-slate-800">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Shopper Profile</h2>
          <button className="btn-ghost" onClick={onClose} aria-label="Close">
            <IconX />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {shopper.loading && !shopper.data ? (
            <Loading label="Loading shopper…" />
          ) : shopper.data ? (
            <>
              <div className="flex items-center gap-3">
                <Avatar name={shopper.data.name} className="h-12 w-12" />
                <div>
                  <div className="text-base font-bold text-slate-900 dark:text-white">{shopper.data.name}</div>
                  <div className="text-xs text-slate-400">{shopper.data.email}</div>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-lg bg-slate-50 py-2 dark:bg-slate-800/50">
                  <div className="text-lg font-bold text-slate-900 dark:text-white">{shopper.data.rating?.toFixed(1)}★</div>
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Rating</div>
                </div>
                <div className="rounded-lg bg-slate-50 py-2 dark:bg-slate-800/50">
                  <div className="text-lg font-bold text-slate-900 dark:text-white">
                    {Math.round((shopper.data.completion_rate || 0) * 100)}%
                  </div>
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Completion</div>
                </div>
                <div className="rounded-lg bg-slate-50 py-2 dark:bg-slate-800/50">
                  <div className="text-lg font-bold text-slate-900 dark:text-white">{shopper.data.previous_assignments}</div>
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Jobs</div>
                </div>
              </div>

              {shopper.data.experience_description && (
                <p className="mt-4 text-sm text-slate-600 dark:text-slate-400">{shopper.data.experience_description}</p>
              )}

              <div className="mt-6">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100">
                  <IconHistory width={16} height={16} /> Campaign History
                  {history.data && (
                    <span className="text-xs font-normal text-slate-400">
                      {history.data.counts.completed} completed · {history.data.counts.declined} declined ·{" "}
                      {history.data.counts.pending} pending
                    </span>
                  )}
                </div>

                {history.loading && !history.data ? (
                  <Loading label="Loading history…" />
                ) : !history.data?.items.length ? (
                  <div className="rounded-lg border border-dashed border-slate-200 py-8 text-center text-sm text-slate-400 dark:border-slate-700">
                    No invitations for this shopper yet.
                  </div>
                ) : (
                  <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                    {history.data.items.map((h: any) => (
                      <li key={h.invitation_id} className="flex items-center justify-between py-2.5">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                            {h.client_name ? `${h.client_name} — ` : ""}
                            {h.campaign_name}
                          </div>
                          <div className="text-xs text-slate-400">
                            {h.shop_name} · {h.reference} · {fmtDate(h.responded_at || h.created_at)}
                          </div>
                        </div>
                        <Badge className={statusBadgeClass(STATUS_KEY[h.status] || "created")}>{h.status}</Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
