import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import { MapContainer, Marker, Popup, TileLayer } from "react-leaflet";
import { IconX } from "./Icons";
import { Badge, Loading } from "./ui";
import { api } from "../lib/api";
import { fmtDate, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "../pages/Dashboard";

// How often the map re-polls shop coverage and shopper availability — this is
// what makes "available shoppers near this shop" a live view rather than a
// one-time snapshot: a shopper going unavailable, a new invitation, or a
// coverage change shows up here within one interval, no page reload needed.
const MAP_REFRESH_MS = 10000;

// Polls at a fixed cadence without needing a stable callback identity from
// the caller — the latest `tick` is always invoked, but the interval itself
// is only created once per `intervalMs`, so an inline arrow function doesn't
// reset the timer on every render (which would otherwise starve it forever
// whenever something else re-renders the component more often than intervalMs).
function useLiveReload(tick: () => void, intervalMs: number) {
  const tickRef = useRef(tick);
  tickRef.current = tick;
  useEffect(() => {
    const id = window.setInterval(() => tickRef.current(), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
}

function relativeSeconds(since: number | null): string {
  if (since == null) return "";
  const secs = Math.max(0, Math.round((Date.now() - since) / 1000));
  if (secs < 2) return "just now";
  if (secs < 60) return `${secs}s ago`;
  return `${Math.round(secs / 60)}m ago`;
}

const COVERAGE_HEX: Record<string, string> = {
  healthy: "#10b981",
  medium: "#f59e0b",
  low: "#f43f5e",
};

const SHOPPER_MARKER_MIN = 10;

function shopIcon(coverage: string) {
  const color = COVERAGE_HEX[coverage] || "#64748b";
  return L.divIcon({
    className: "",
    html: `<div style="width:18px;height:18px;border-radius:9999px;background:${color};border:2.5px solid white;box-shadow:0 1px 5px rgba(0,0,0,0.45)"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    popupAnchor: [0, -10],
  });
}

function shopperIcon(rank: number) {
  // Top 3 candidates stand out in brand purple; the rest are a quieter dot
  // — signals "these are the shoppers to contact first", not just "nearby".
  const color = rank <= 3 ? "#6366f1" : "#94a3b8";
  const size = rank <= 3 ? 11 : 8;
  return L.divIcon({
    className: "",
    html: `<div style="width:${size}px;height:${size}px;border-radius:9999px;background:${color};border:1.5px solid white;box-shadow:0 1px 3px rgba(0,0,0,0.4)"></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -size / 2],
  });
}

const INDIA_CENTER: [number, number] = [20.5937, 78.9629];

export function CampaignMapTab({
  campaignId,
  onOpenDetail,
}: {
  campaignId: string;
  onOpenDetail: (shopId: string) => void;
}) {
  const { data, loading, error, reload } = useApi(() => api.campaignMap(campaignId), [campaignId]);
  const mapRef = useRef<L.Map | null>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [, forceTick] = useState(0);

  useLiveReload(() => {
    reload();
    setLastUpdated(Date.now());
  }, MAP_REFRESH_MS);

  // Re-render every few seconds purely to refresh the "Xs ago" label text —
  // doesn't touch data, so it never disturbs an open popup or the map's pan/zoom.
  useEffect(() => {
    const id = window.setInterval(() => forceTick((t) => t + 1), 5000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (data) setLastUpdated((prev) => prev ?? Date.now());
  }, [data]);

  if (loading && !data) return <Loading label="Loading map…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  const items = data.items as any[];
  const located = items.filter((s) => s.latitude != null && s.longitude != null);
  const bounds: [number, number][] = located.map((s) => [s.latitude, s.longitude]);

  function openShop(shopId: string) {
    // Close any open shop popup first — otherwise it stays rendered behind
    // the Shop Detail drawer and the two overlap into a confusing mess.
    mapRef.current?.closePopup();
    onOpenDetail(shopId);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
        <span className="inline-flex items-center gap-1.5 font-semibold text-emerald-600 dark:text-emerald-400">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          </span>
          Live
        </span>
        <span>Updated {relativeSeconds(lastUpdated)}</span>
        <LegendDot color={COVERAGE_HEX.healthy} label="Healthy coverage" />
        <LegendDot color={COVERAGE_HEX.medium} label="Medium coverage" />
        <LegendDot color={COVERAGE_HEX.low} label="Low coverage" />
        <LegendDot color="#6366f1" label="Top-matched shopper" />
        <LegendDot color="#94a3b8" label="Other eligible shopper" />
        {items.length > located.length && (
          <span className="text-amber-600 dark:text-amber-400">
            {items.length - located.length} shop(s) missing coordinates — not shown on map
          </span>
        )}
      </div>

      <div className="card isolate relative z-0 overflow-hidden p-0" style={{ height: 480 }}>
        {located.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-400">
            No shops with coordinates in this campaign yet.
          </div>
        ) : (
          <MapContainer
            ref={mapRef}
            {...(bounds.length ? { bounds } : { center: INDIA_CENTER, zoom: 5 })}
            boundsOptions={{ padding: [40, 40] }}
            style={{ height: "100%", width: "100%" }}
            scrollWheelZoom
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {located.map((s) => (
              <Marker key={s.id} position={[s.latitude, s.longitude]} icon={shopIcon(s.coverage)}>
                <Popup>
                  <div className="min-w-[200px] text-sm">
                    <div className="font-bold text-slate-900">{s.shop_name}</div>
                    <div className="text-xs text-slate-500">
                      {[s.city, s.state].filter(Boolean).join(", ") || "—"}
                    </div>
                    <div className="mt-1 text-xs">
                      Status: <span className="font-semibold">{s.status}</span>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
                      <div>
                        Required: <span className="font-semibold">{s.required_shoppers}</span>
                      </div>
                      <div>
                        Available: <span className="font-semibold">{s.available_shoppers}</span>
                      </div>
                      <div>
                        Invited: <span className="font-semibold">{s.invited_shoppers}</span>
                      </div>
                      <div>
                        Accepted: <span className="font-semibold">{s.accepted_shoppers}</span>
                      </div>
                    </div>
                    <button
                      className="btn-primary mt-2.5 w-full !py-1.5 text-xs"
                      onClick={() => openShop(s.id)}
                    >
                      View Shop
                    </button>
                  </div>
                </Popup>
              </Marker>
            ))}
            {located.map((s) => (
              <ShopperMarkers key={`shoppers-${s.id}`} campaignId={campaignId} shop={s} />
            ))}
          </MapContainer>
        )}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Plots the top AI-matched, located shoppers around a shop so the map answers
// "who's actually nearby and eligible", not just an aggregate count in a
// popup. Reuses the same /recommendations ranking the Recommendations tab
// and Shop Detail drawer use — one matching engine, three presentations.
// --------------------------------------------------------------------------- //
function ShopperMarkers({ campaignId, shop }: { campaignId: string; shop: any }) {
  const { data, reload } = useApi(
    () => api.aiShopRecommendations(campaignId, shop.id, { limit: SHOPPER_MARKER_MIN }),
    [campaignId, shop.id]
  );
  useLiveReload(reload, MAP_REFRESH_MS);

  const recs = (data?.recommendations || []) as any[];
  const located = recs.filter((r) => r.latitude != null && r.longitude != null);

  return (
    <>
      {located.map((r, i) => (
        <Marker key={r.shopper_id} position={[r.latitude, r.longitude]} icon={shopperIcon(i + 1)}>
          <Popup>
            <div className="min-w-[180px] text-sm">
              <div className="font-bold text-slate-900">
                {i + 1}. {r.name}
              </div>
              <div className="text-xs text-slate-500">For {shop.shop_name}</div>
              <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
                <div>
                  Match: <span className="font-semibold">{r.match_score}%</span>
                </div>
                <div>
                  Distance: <span className="font-semibold">{r.distance_km != null ? `${r.distance_km} km` : "—"}</span>
                </div>
                <div className="col-span-2">
                  Availability: <span className="font-semibold capitalize">{r.availability || "—"}</span>
                </div>
              </div>
            </div>
          </Popup>
        </Marker>
      ))}
    </>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

// --------------------------------------------------------------------------- //
// Shop Detail panel — opened from a map marker. Read-only summary of the shop
// + campaign fields plus AI-ranked candidates (reuses the exact same
// /recommendations endpoint the Recommendations tab uses — no second
// matching engine). Selecting/approving happens in the Recommendations tab
// (via "Open in Recommendations"), so there's exactly one place that owns
// the select/override/approve state.
// --------------------------------------------------------------------------- //
export function ShopDetailDrawer({
  campaignId,
  campaignName,
  shopId,
  onClose,
  onOpenRecommendations,
}: {
  campaignId: string;
  campaignName: string;
  shopId: string;
  onClose: () => void;
  onOpenRecommendations: (shopId: string) => void;
}) {
  const shop = useApi(() => api.shop(shopId), [shopId]);
  const recs = useApi(() => api.aiShopRecommendations(campaignId, shopId, { limit: 5 }), [campaignId, shopId]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-md flex-col overflow-hidden bg-white shadow-2xl dark:bg-slate-900 sm:max-w-lg">
        <div className="flex items-center justify-between border-b border-slate-200 p-4 dark:border-slate-800">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Shop Detail</h2>
          <button className="btn-ghost" onClick={onClose} aria-label="Close">
            <IconX />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {shop.loading && !shop.data ? (
            <Loading label="Loading shop…" />
          ) : shop.error ? (
            <ErrorBox message={shop.error} onRetry={shop.reload} />
          ) : shop.data ? (
            <>
              <div className="text-lg font-bold text-slate-900 dark:text-white">{shop.data.shop_name}</div>
              <div className="text-sm text-slate-500 dark:text-slate-400">
                {[shop.data.address, shop.data.city, shop.data.state].filter(Boolean).join(", ") || "—"}
              </div>
              {shop.data.latitude != null && (
                <div className="text-xs text-slate-400">
                  {shop.data.latitude.toFixed(4)}, {shop.data.longitude.toFixed(4)}
                </div>
              )}

              <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <DetailField label="Campaign" value={campaignName} />
                <DetailField label="Status" value={<Badge className={statusBadgeClass(shop.data.status === "open" ? "sent" : "created")}>{shop.data.status}</Badge>} />
                <DetailField label="Deadline" value={fmtDate(shop.data.visit_end)} />
                <DetailField label="Compensation" value={`${shop.data.currency} ${shop.data.compensation}`} />
                <DetailField label="Category" value={shop.data.category || "—"} />
                <DetailField label="Required shoppers" value={shop.data.required_shoppers} />
              </dl>

              <div className="mt-6">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Top AI-matched shoppers</h3>
                  <button
                    className="text-xs font-semibold text-brand-600 hover:underline dark:text-brand-400"
                    onClick={() => onOpenRecommendations(shopId)}
                  >
                    Open in Recommendations →
                  </button>
                </div>

                {recs.loading && !recs.data ? (
                  <Loading label="Ranking candidates…" />
                ) : recs.error ? (
                  <ErrorBox message={recs.error} onRetry={recs.reload} />
                ) : !recs.data?.recommendations?.length ? (
                  <div className="rounded-lg border border-dashed border-slate-200 py-8 text-center text-sm text-slate-400 dark:border-slate-700">
                    No eligible candidates for this shop yet.
                  </div>
                ) : (
                  <ul className="space-y-2">
                    {recs.data.recommendations.slice(0, 5).map((r: any, i: number) => (
                      <li key={r.shopper_id} className="rounded-lg border border-slate-100 p-3 dark:border-slate-800">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                            {i + 1}. {r.name}
                          </span>
                          <span className="text-sm font-bold text-brand-600 dark:text-brand-400">{r.match_score}%</span>
                        </div>
                        {r.reasons?.length > 0 && (
                          <ul className="mt-1 space-y-0.5 text-xs text-slate-500 dark:text-slate-400">
                            {r.reasons.slice(0, 3).map((reason: string, j: number) => (
                              <li key={j}>• {reason}</li>
                            ))}
                          </ul>
                        )}
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

function DetailField({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <dt className="text-xs text-slate-400">{label}</dt>
      <dd className="mt-0.5 font-semibold text-slate-800 dark:text-slate-100">{value ?? "—"}</dd>
    </div>
  );
}
