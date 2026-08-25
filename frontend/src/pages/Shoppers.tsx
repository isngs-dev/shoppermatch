import { useState } from "react";
import { ShopperDrawer } from "../components/ShopperDrawer";
import { Avatar, Badge, Loading } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

const AVAIL_CLASS: Record<string, string> = {
  available: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  limited: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  busy: "bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300",
  unavailable: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
};

export function Shoppers() {
  const [q, setQ] = useState("");
  const [availability, setAvailability] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data, loading, error, reload } = useApi(
    () => api.shoppers(q, availability),
    [q, availability]
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <input
          className="input h-9 w-64"
          placeholder="Search name, email, city…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select className="input h-9 w-44" value={availability} onChange={(e) => setAvailability(e.target.value)}>
          <option value="">All availability</option>
          <option value="available">Available</option>
          <option value="limited">Limited</option>
          <option value="busy">Busy</option>
          <option value="unavailable">Unavailable</option>
        </select>
      </div>

      {error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : loading && !data ? (
        <Loading label="Loading shoppers…" />
      ) : (
        <div className="card overflow-x-auto">
          <table className="min-w-full">
            <thead className="border-b border-slate-100 dark:border-slate-800">
              <tr>
                <th className="th">Shopper</th>
                <th className="th hidden md:table-cell">Location</th>
                <th className="th">Categories</th>
                <th className="th">Availability</th>
                <th className="th text-right">Rating</th>
                <th className="th text-right">Completion</th>
                <th className="th text-right hidden lg:table-cell">Jobs</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
              {data.items.map((s: any) => (
                <tr
                  key={s.id}
                  className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40"
                  onClick={() => setSelectedId(s.id)}
                >
                  <td className="td">
                    <div className="flex items-center gap-3">
                      <Avatar name={s.name} />
                      <div>
                        <div className="font-medium text-slate-800 dark:text-slate-100">{s.name}</div>
                        <div className="text-xs text-slate-400">{s.email}</div>
                      </div>
                    </div>
                  </td>
                  <td className="td hidden md:table-cell">
                    {s.city}
                    <div className="text-xs text-slate-400">{s.source}</div>
                  </td>
                  <td className="td">
                    <div className="flex flex-wrap gap-1">
                      {(s.categories || []).slice(0, 3).map((c: string) => (
                        <span key={c} className="badge bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                          {c}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="td">
                    <Badge className={AVAIL_CLASS[s.availability_status] || AVAIL_CLASS.unavailable}>
                      {s.availability_status}
                    </Badge>
                  </td>
                  <td className="td text-right font-semibold">{s.rating.toFixed(1)}★</td>
                  <td className="td text-right">{Math.round(s.completion_rate * 100)}%</td>
                  <td className="td hidden text-right lg:table-cell">{s.previous_assignments}</td>
                </tr>
              ))}
              {data.items.length === 0 && (
                <tr>
                  <td colSpan={7} className="td py-10 text-center text-slate-400">
                    No shoppers found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {selectedId && <ShopperDrawer shopperId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  );
}
