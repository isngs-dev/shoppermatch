import { useEffect, useState } from "react";
import { Badge, Loading } from "../components/ui";
import { api } from "../lib/api";
import { classNames, fmtDate, fmtMoney, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

export function Shops() {
  const campaigns = useApi(() => api.campaigns());
  const [campaignId, setCampaignId] = useState("");
  const shops = useApi(() => api.shops(campaignId || undefined), [campaignId]);

  useEffect(() => {
    // default to all
  }, [campaigns.data]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <select className="input h-9 w-72" value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
          <option value="">All campaigns</option>
          {campaigns.data?.items.map((c: any) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      {shops.error ? (
        <ErrorBox message={shops.error} onRetry={shops.reload} />
      ) : shops.loading && !shops.data ? (
        <Loading label="Loading shops…" />
      ) : (
        <div className="card overflow-x-auto">
          <table className="min-w-full">
            <thead className="border-b border-slate-100 dark:border-slate-800">
              <tr>
                <th className="th">Shop</th>
                <th className="th hidden md:table-cell">Location</th>
                <th className="th">Category</th>
                <th className="th text-right">Compensation</th>
                <th className="th text-center">Shoppers</th>
                <th className="th hidden lg:table-cell">Visit window</th>
                <th className="th">Status</th>
                <th className="th">Bonus</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
              {shops.data.items.map((s: any) => (
                <tr key={s.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                  <td className="td font-medium text-slate-800 dark:text-slate-100">{s.shop_name}</td>
                  <td className="td hidden md:table-cell">
                    {s.city}, {s.state}
                  </td>
                  <td className="td">
                    <span className="badge bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {s.category}
                    </span>
                  </td>
                  <td className="td text-right font-semibold text-emerald-600 dark:text-emerald-400">
                    {fmtMoney(s.compensation, s.currency)}
                  </td>
                  <td className="td text-center">{s.required_shoppers}</td>
                  <td className="td hidden text-slate-500 lg:table-cell">
                    {fmtDate(s.visit_start)} – {fmtDate(s.visit_end)}
                  </td>
                  <td className="td">
                    <Badge className={statusBadgeClass(s.status === "open" ? "sent" : s.status === "completed" ? "completed" : "created")}>
                      {s.status}
                    </Badge>
                  </td>
                  <td className="td">
                    {s.bonus ? (
                      <span
                        className={classNames(
                          "badge",
                          s.bonus.completed_at
                            ? "bg-teal-100 text-teal-700 dark:bg-teal-950 dark:text-teal-300"
                            : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                        )}
                        title={s.bonus.note || undefined}
                      >
                        💰 {fmtMoney(s.bonus.amount, s.bonus.currency)}
                        {s.bonus.completed_at
                          ? ` · Awarded to ${s.bonus.awarded_shopper_name || "shopper"}`
                          : " · Pending"}
                      </span>
                    ) : (
                      <span className="text-slate-300 dark:text-slate-600">—</span>
                    )}
                  </td>
                </tr>
              ))}
              {shops.data.items.length === 0 && (
                <tr>
                  <td colSpan={8} className="td py-10 text-center text-slate-400">
                    No shops found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
