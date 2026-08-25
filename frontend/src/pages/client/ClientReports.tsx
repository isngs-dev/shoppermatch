import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, EmptyState, Loading, useToast } from "../../components/ui";
import { api } from "../../lib/api";
import { useApi } from "../../lib/useApi";
import { ErrorBox } from "../Dashboard";

const FUNNEL_COLORS = ["#0ea5e9", "#6366f1", "#8b5cf6", "#10b981", "#f43f5e"];

export function ClientReports() {
  const { data, loading, error, reload } = useApi(() => api.clientReports());
  const toast = useToast();
  const [exporting, setExporting] = useState<string | null>(null);
  if (loading && !data) return <Loading label="Loading reports…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  async function doExport(campaignId: string, campaignName: string, format: "csv" | "xlsx" | "pdf") {
    const key = `${campaignId}:${format}`;
    setExporting(key);
    try {
      await api.exportClientCampaignReport(campaignId, format, campaignName);
    } catch (e: any) {
      toast(e?.message || "Export failed", "error");
    } finally {
      setExporting(null);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Reports</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Campaign summary, recruitment coverage, and outreach performance across your campaigns.
        </p>
      </div>

      {!data.items.length ? (
        <div className="card">
          <EmptyState title="No campaigns yet" />
        </div>
      ) : (
        <div className="space-y-4">
          {data.items.map((r: any) => (
            <div key={r.campaign_id} className="card p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-semibold text-slate-900 dark:text-white">{r.campaign_name}</h3>
                <div className="flex items-center gap-2">
                  <Badge className="bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{r.bucket}</Badge>
                  <div className="flex gap-1">
                    {(["pdf", "xlsx", "csv"] as const).map((fmt) => (
                      <button
                        key={fmt}
                        className="btn-ghost !px-2 !py-1 text-xs uppercase"
                        disabled={exporting === `${r.campaign_id}:${fmt}`}
                        onClick={() => doExport(r.campaign_id, r.campaign_name, fmt)}
                      >
                        {exporting === `${r.campaign_id}:${fmt}` ? "…" : fmt}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {r.ai_summary && (
                <p className="mt-2 text-sm italic text-slate-600 dark:text-slate-300">✨ {r.ai_summary}</p>
              )}

              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <ReportStat label="Campaign Progress" value={`${r.campaign_summary.progress}%`} />
                <ReportStat label="Completion Rate" value={`${r.completion_rate}%`} />
                <ReportStat label="Response Rate" value={`${r.response_rate}%`} />
                <ReportStat
                  label="Recruitment Coverage"
                  value={`${r.recruitment_coverage.confirmed}/${r.recruitment_coverage.required}`}
                />
              </div>

              <div className="mt-4 rounded-lg bg-slate-50 p-3 text-xs text-slate-500 dark:bg-slate-800/50 dark:text-slate-400">
                <span className="font-semibold text-slate-600 dark:text-slate-300">Outreach summary — </span>
                Sent {r.outreach_summary.sent} · Opened {r.outreach_summary.opened} · Clicked {r.outreach_summary.clicked} ·
                Accepted {r.outreach_summary.accepted} · Declined {r.outreach_summary.declined}
              </div>

              <div className="mt-4 h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={[
                      { stage: "Sent", value: r.outreach_summary.sent },
                      { stage: "Opened", value: r.outreach_summary.opened },
                      { stage: "Clicked", value: r.outreach_summary.clicked },
                      { stage: "Accepted", value: r.outreach_summary.accepted },
                      { stage: "Declined", value: r.outreach_summary.declined },
                    ]}
                    margin={{ top: 8, right: 8, bottom: 0, left: -18 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis dataKey="stage" tick={{ fontSize: 12, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 12, fill: "#94a3b8" }} axisLine={false} tickLine={false} allowDecimals={false} />
                    <Tooltip
                      cursor={{ fill: "rgba(99,102,241,0.08)" }}
                      contentStyle={{ borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 12 }}
                    />
                    <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                      {FUNNEL_COLORS.map((color, i) => (
                        <Cell key={i} fill={color} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ReportStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-100 p-3 dark:border-slate-800">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{value}</div>
    </div>
  );
}
