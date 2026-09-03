import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, EmptyState, Loading, Spinner, useToast } from "../../components/ui";
import { IconX } from "../../components/Icons";
import { api } from "../../lib/api";
import { classNames, fmtDateTime } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { ErrorBox } from "../Dashboard";

// Social Media Automation — extends the existing Region-Targeted Social
// Media Posting feature (Campaign Detail's Distribution tab) with a real
// Facebook OAuth connection, a generalized post composer/scheduler, AI
// generation, reusable templates, and the manual/approval workflow for
// Facebook Groups (Meta does not support automated Group posting — see
// backend/app/services/facebook_graph.py).

const TABS = [
  { key: "posts", label: "Posts" },
  { key: "accounts", label: "Connected Accounts" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  pending_approval: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  scheduled: "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  publishing: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300",
  posted: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  posted_manual: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  failed: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  cancelled: "bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500",
  manual_required: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
};
const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  pending_approval: "Pending Approval",
  scheduled: "Scheduled",
  publishing: "Publishing",
  posted: "Published",
  posted_manual: "Published (Manual)",
  failed: "Failed",
  cancelled: "Cancelled",
  manual_required: "Manual Posting Required",
};

export function ClientSocialMedia() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as TabKey) || "posts";

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Social Media</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Create, schedule, and manage social posts generated from your campaigns.
        </p>
      </div>

      <div className="flex gap-1 overflow-x-auto border-b border-slate-200 dark:border-slate-800">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={classNames(
              "shrink-0 border-b-2 px-4 py-2.5 text-sm font-medium transition",
              tab === t.key
                ? "border-brand-600 text-brand-600 dark:text-brand-400"
                : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100"
            )}
            onClick={() => setParams({ tab: t.key })}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "posts" && <PostsTab />}
      {tab === "accounts" && <AccountsTab />}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Posts
// --------------------------------------------------------------------------- //
function PostsTab() {
  const posts = useApi(() => api.socialPosts());
  const campaigns = useApi(() => api.campaigns());
  const [composerOpen, setComposerOpen] = useState(false);
  const [editingPost, setEditingPost] = useState<any | null>(null);
  const toast = useToast();

  if (posts.error) return <ErrorBox message={posts.error} onRetry={posts.reload} />;
  if (posts.loading && !posts.data) return <Loading label="Loading posts…" />;

  const items = posts.data?.items || [];

  async function action(fn: () => Promise<any>, successMsg?: string) {
    try {
      await fn();
      if (successMsg) toast(successMsg, "success");
      posts.reload();
    } catch (e: any) {
      toast(e?.message || "Action failed", "error");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button
          className="btn-primary"
          onClick={() => {
            setEditingPost(null);
            setComposerOpen(true);
          }}
        >
          + New Post
        </button>
      </div>

      {items.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No social posts yet"
            hint="Generate a post from one of your campaigns or shops to get started."
          />
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((p: any) => (
            <div key={p.id} className="card flex flex-wrap items-start justify-between gap-3 p-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge className={STATUS_STYLES[p.status] || STATUS_STYLES.draft}>
                    {STATUS_LABELS[p.status] || p.status}
                  </Badge>
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                    {p.destination_type} · {p.target_kind}
                  </span>
                  <span className="text-xs text-slate-400">{p.campaign_name}</span>
                  {p.source_shop_name && <span className="text-xs text-slate-400">· {p.source_shop_name}</span>}
                </div>
                <p className="mt-2 line-clamp-2 text-sm text-slate-700 dark:text-slate-200">{p.message}</p>
                <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-400">
                  {p.target_ref && <span>Target: {p.target_ref}</span>}
                  {p.scheduled_at && <span>Scheduled: {fmtDateTime(p.scheduled_at)} ({p.timezone})</span>}
                  {p.posted_at && (p.status === "posted" || p.status === "posted_manual") && (
                    <span>Posted: {fmtDateTime(p.posted_at)}</span>
                  )}
                  {p.retry_count > 0 && <span>Retries: {p.retry_count}</span>}
                </div>
                {p.error_message && (
                  <p className="mt-1.5 text-xs font-medium text-rose-600 dark:text-rose-400">{p.error_message}</p>
                )}
              </div>
              {p.image_url && (
                <img src={p.image_url} alt="" className="h-16 w-16 shrink-0 rounded-lg object-cover" />
              )}
              <div className="flex shrink-0 flex-wrap gap-1.5">
                {["draft", "pending_approval", "scheduled", "failed"].includes(p.status) && (
                  <button
                    className="btn-secondary h-8 px-2.5 text-xs"
                    onClick={() => {
                      setEditingPost(p);
                      setComposerOpen(true);
                    }}
                  >
                    Edit
                  </button>
                )}
                {p.target_kind === "group" && p.status === "manual_required" && (
                  <button
                    className="btn-primary h-8 px-2.5 text-xs"
                    onClick={() => action(() => api.markSocialPostPosted(p.id), "Marked as posted.")}
                  >
                    Mark as Posted
                  </button>
                )}
                {p.target_kind === "page" && ["draft", "pending_approval", "failed"].includes(p.status) && (
                  <button
                    className="btn-secondary h-8 px-2.5 text-xs"
                    onClick={() => action(() => api.publishSocialPostNow(p.id), "Published.")}
                  >
                    Publish Now
                  </button>
                )}
                {["scheduled", "failed"].includes(p.status) && p.target_kind === "page" && (
                  <button
                    className="btn-secondary h-8 px-2.5 text-xs"
                    onClick={() => action(() => api.cancelSocialPost(p.id), "Cancelled.")}
                  >
                    Cancel
                  </button>
                )}
                <button
                  className="btn-secondary h-8 px-2.5 text-xs"
                  onClick={() => action(() => api.duplicateSocialPost(p.id), "Duplicated.")}
                >
                  Duplicate
                </button>
                {["draft", "cancelled", "failed"].includes(p.status) && (
                  <button
                    className="btn-secondary h-8 px-2.5 text-xs text-rose-600 dark:text-rose-400"
                    onClick={() => {
                      if (confirm("Delete this post?")) action(() => api.deleteSocialPost(p.id), "Deleted.");
                    }}
                  >
                    Delete
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {composerOpen && (
        <ComposerModal
          post={editingPost}
          campaigns={campaigns.data?.items || []}
          onClose={() => setComposerOpen(false)}
          onSaved={() => {
            setComposerOpen(false);
            posts.reload();
          }}
        />
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Composer
// --------------------------------------------------------------------------- //
function ComposerModal({
  post,
  campaigns,
  onClose,
  onSaved,
}: {
  post: any | null;
  campaigns: any[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const isEdit = !!post;
  const [campaignId, setCampaignId] = useState(post?.campaign_id || campaigns[0]?.id || "");
  const [sourceType, setSourceType] = useState<"campaign" | "shop">(post?.source_type || "campaign");
  const [shopId, setShopId] = useState(post?.source_shop_id || "");
  const [platform, setPlatform] = useState(post?.destination_type || "facebook");
  const [targetKind, setTargetKind] = useState<"page" | "group">(post?.target_kind || "page");
  const [targetRef, setTargetRef] = useState(post?.target_ref || "");
  const [message, setMessage] = useState(post?.message || "");
  const [imageUrl, setImageUrl] = useState(post?.image_url || "");
  const [scheduledDate, setScheduledDate] = useState("");
  const [scheduledTime, setScheduledTime] = useState("");
  const [timezone, setTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [busy, setBusy] = useState<string | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiTone, setAiTone] = useState("professional");
  const [aiLanguage, setAiLanguage] = useState("English");
  const [aiInstructions, setAiInstructions] = useState("");

  const shops = useApi(() => (campaignId ? api.campaignShops(campaignId) : Promise.resolve({ items: [] })), [campaignId]);
  const accounts = useApi(() => api.clientSocialAccounts());

  const connectedPlatforms = (accounts.data?.items || []).filter((a: any) => a.connected);
  const charCount = message.length;

  async function generateWithAi() {
    if (!isEdit) {
      toast("Save as a draft first, then generate with AI.", "info");
      return;
    }
    setBusy("ai");
    try {
      const res = await api.generateSocialPostText(post.id, { tone: aiTone, language: aiLanguage, instructions: aiInstructions || undefined });
      setMessage(res.message);
      setAiOpen(false);
      toast("Generated a draft — review before publishing.", "success");
    } catch (e: any) {
      toast(e?.message || "AI generation failed", "error");
    } finally {
      setBusy(null);
    }
  }

  async function generateImage() {
    if (!isEdit) {
      toast("Save as a draft first, then generate an image.", "info");
      return;
    }
    setBusy("image");
    try {
      const res = await api.generateSocialPostImage(post.id);
      setImageUrl(res.image_url);
      toast("Image generated.", "success");
    } catch (e: any) {
      toast(e?.message || "Image generation failed", "error");
    } finally {
      setBusy(null);
    }
  }

  async function save(kind: "draft" | "schedule" | "publish") {
    setBusy(kind);
    try {
      let current = post;
      const body = { campaign_id: campaignId, source_type: sourceType, source_shop_id: sourceType === "shop" ? shopId : undefined, destination_type: platform, target_kind: targetKind, target_ref: targetRef || undefined, message, image_url: imageUrl || undefined };
      if (!current) {
        current = await api.createSocialPost(body);
      } else {
        current = await api.updateSocialPost(current.id, { message, image_url: imageUrl || undefined, target_ref: targetRef || undefined });
      }
      if (kind === "schedule") {
        if (!scheduledDate || !scheduledTime) {
          toast("Choose a date and time to schedule.", "error");
          setBusy(null);
          return;
        }
        const iso = new Date(`${scheduledDate}T${scheduledTime}`).toISOString();
        await api.scheduleSocialPost(current.id, iso, timezone);
        toast("Post scheduled.", "success");
      } else if (kind === "publish") {
        await api.publishSocialPostNow(current.id);
        toast("Published.", "success");
      } else {
        toast("Draft saved.", "success");
      }
      onSaved();
    } catch (e: any) {
      toast(e?.message || "Failed to save post", "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative my-8 w-full max-w-2xl rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-900 dark:text-white">{isEdit ? "Edit Post" : "New Social Post"}</h3>
          <button className="btn-ghost" onClick={onClose} aria-label="Close">
            <IconX />
          </button>
        </div>

        <div className="mt-4 space-y-4">
          {!isEdit && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Campaign</label>
                  <select className="input" value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
                    {campaigns.map((c: any) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">Generate from</label>
                  <select className="input" value={sourceType} onChange={(e) => setSourceType(e.target.value as any)}>
                    <option value="campaign">Whole Campaign</option>
                    <option value="shop">One Shop</option>
                  </select>
                </div>
              </div>
              {sourceType === "shop" && (
                <div>
                  <label className="label">Shop</label>
                  <select className="input" value={shopId} onChange={(e) => setShopId(e.target.value)}>
                    <option value="">Select a shop…</option>
                    {(shops.data?.items || []).map((s: any) => (
                      <option key={s.id} value={s.id}>{s.shop_name} — {s.city}</option>
                    ))}
                  </select>
                </div>
              )}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Platform</label>
                  <select className="input" value={platform} onChange={(e) => setPlatform(e.target.value)}>
                    {connectedPlatforms.length === 0 ? (
                      <option value="facebook">facebook (not connected)</option>
                    ) : (
                      connectedPlatforms.map((a: any) => (
                        <option key={a.platform} value={a.platform}>{a.label}</option>
                      ))
                    )}
                  </select>
                </div>
                <div>
                  <label className="label">Target type</label>
                  <select className="input" value={targetKind} onChange={(e) => setTargetKind(e.target.value as any)}>
                    <option value="page">Page (can auto-publish)</option>
                    <option value="group">Group (manual posting)</option>
                  </select>
                </div>
              </div>
              {targetKind === "group" && (
                <div>
                  <label className="label">Group name or URL</label>
                  <input className="input" value={targetRef} onChange={(e) => setTargetRef(e.target.value)} placeholder="e.g. https://facebook.com/groups/..." />
                  <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                    Meta does not support automated posting to Facebook Groups. You'll copy this post and publish it
                    yourself, then mark it as posted here.
                  </p>
                </div>
              )}
            </>
          )}

          {isEdit && targetKind === "group" && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
              Target: {targetRef || "Facebook Group"} — manual posting required.
            </p>
          )}

          <div>
            <div className="flex items-center justify-between">
              <label className="label !mb-0">Post text</label>
              <span className="text-xs text-slate-400">{charCount} characters</span>
            </div>
            <textarea
              className="input min-h-[140px] resize-y"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Write your post, or use AI generation below…"
            />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button type="button" className="btn-secondary h-8 px-2.5 text-xs" onClick={() => setAiOpen((v) => !v)}>
                ✨ Generate with AI
              </button>
              <button type="button" className="btn-secondary h-8 px-2.5 text-xs" onClick={generateImage} disabled={busy === "image"}>
                {busy === "image" ? <Spinner className="h-3.5 w-3.5" /> : null} Generate Image
              </button>
            </div>
            {aiOpen && (
              <div className="mt-2 space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                <div className="grid grid-cols-2 gap-2">
                  <select className="input h-9" value={aiTone} onChange={(e) => setAiTone(e.target.value)}>
                    <option value="professional">Professional</option>
                    <option value="friendly">Friendly</option>
                    <option value="promotional">Promotional</option>
                    <option value="short">Short</option>
                  </select>
                  <input className="input h-9" value={aiLanguage} onChange={(e) => setAiLanguage(e.target.value)} placeholder="Language" />
                </div>
                <input className="input h-9" value={aiInstructions} onChange={(e) => setAiInstructions(e.target.value)} placeholder="Optional instructions…" />
                <button type="button" className="btn-primary h-8 px-3 text-xs" onClick={generateWithAi} disabled={busy === "ai"}>
                  {busy === "ai" ? <Spinner className="h-3.5 w-3.5" /> : null} Generate
                </button>
              </div>
            )}
          </div>

          {(imageUrl || message) && (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800/40">
              <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Preview</div>
              {imageUrl && <img src={imageUrl} alt="" className="mb-2 max-h-56 w-full rounded-lg object-cover" />}
              <p className="whitespace-pre-wrap text-sm text-slate-700 dark:text-slate-200">{message || "…"}</p>
            </div>
          )}

          {targetKind === "page" && (
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="label">Date</label>
                <input type="date" className="input" value={scheduledDate} onChange={(e) => setScheduledDate(e.target.value)} />
              </div>
              <div>
                <label className="label">Time</label>
                <input type="time" className="input" value={scheduledTime} onChange={(e) => setScheduledTime(e.target.value)} />
              </div>
              <div>
                <label className="label">Timezone</label>
                <input className="input" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
              </div>
            </div>
          )}
        </div>

        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-secondary" onClick={() => save("draft")} disabled={!!busy || !message}>
            {busy === "draft" ? <Spinner /> : null} Save Draft
          </button>
          {targetKind === "page" && (
            <>
              <button className="btn-secondary" onClick={() => save("schedule")} disabled={!!busy || !message}>
                {busy === "schedule" ? <Spinner /> : null} Schedule
              </button>
              <button className="btn-primary" onClick={() => save("publish")} disabled={!!busy || !message}>
                {busy === "publish" ? <Spinner /> : null} Publish Now
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Connected Accounts
// --------------------------------------------------------------------------- //
function AccountsTab() {
  const accounts = useApi(() => api.clientSocialAccounts());
  const fbStatus = useApi(() => api.facebookStatus());
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const [pendingPages, setPendingPages] = useState<any[] | null>(null);
  const [connecting, setConnecting] = useState<string | null>(null);

  const fbPending = params.get("fb_pending");
  const fbError = params.get("fb_error");

  useEffect(() => {
    if (fbError) {
      toast(decodeURIComponent(fbError), "error");
      setParams({}, { replace: true });
    }
  }, [fbError]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (fbPending) {
      api
        .facebookPendingPages(fbPending)
        .then((r: any) => setPendingPages(r.pages))
        .catch((e: any) => toast(e?.message || "Connection expired — try again.", "error"))
        .finally(() => setParams({}, { replace: true }));
    }
  }, [fbPending]); // eslint-disable-line react-hooks/exhaustive-deps

  async function connectFacebookReal() {
    setConnecting("facebook");
    try {
      const res = await api.facebookConnect();
      window.location.href = res.authorize_url;
    } catch (e: any) {
      toast(e?.message || "Failed to start Facebook connection", "error");
      setConnecting(null);
    }
  }

  async function connectDemo(platform: string) {
    setConnecting(platform);
    try {
      await api.connectSocialAccount(platform);
      toast(`Connected ${platform} (demo).`, "success");
      accounts.reload();
    } catch (e: any) {
      toast(e?.message || "Failed to connect", "error");
    } finally {
      setConnecting(null);
    }
  }

  async function disconnect(platform: string) {
    if (!confirm(`Disconnect ${platform}?`)) return;
    try {
      await api.disconnectSocialAccount(platform);
      toast(`Disconnected ${platform}.`, "success");
      accounts.reload();
    } catch (e: any) {
      toast(e?.message || "Failed to disconnect", "error");
    }
  }

  if (accounts.error) return <ErrorBox message={accounts.error} onRetry={accounts.reload} />;
  if (accounts.loading && !accounts.data) return <Loading label="Loading connected accounts…" />;

  return (
    <div className="space-y-4">
      {pendingPages && (
        <PagePicker
          pages={pendingPages}
          onCancel={() => setPendingPages(null)}
          onSelected={async (pageId, pendingId) => {
            try {
              await api.facebookSelectPage(pendingId, pageId);
              toast("Facebook Page connected.", "success");
              setPendingPages(null);
              accounts.reload();
            } catch (e: any) {
              toast(e?.message || "Failed to connect that Page", "error");
            }
          }}
          pendingId={fbPending || ""}
        />
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {(accounts.data?.items || []).map((a: any) => (
          <div key={a.platform} className="card p-4">
            <div className="flex items-center justify-between">
              <div className="font-semibold text-slate-800 dark:text-slate-100">{a.label}</div>
              {a.connected && (
                <Badge
                  className={
                    a.needs_reconnect
                      ? "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300"
                      : a.is_real_connection
                      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                      : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                  }
                >
                  {a.needs_reconnect ? "Reconnect needed" : a.is_real_connection ? "Connected (Live)" : "Connected (Demo)"}
                </Badge>
              )}
            </div>
            {a.connected && <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{a.account_name}</div>}

            {a.platform === "facebook" && fbStatus.data?.configured ? (
              <p className="mt-2 text-xs text-slate-400">Real Meta OAuth is configured for this account.</p>
            ) : a.platform === "facebook" ? (
              <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
                Real Facebook OAuth isn't configured yet (FACEBOOK_APP_ID/SECRET) — using demo mode.
              </p>
            ) : null}

            <div className="mt-3">
              {!a.connected ? (
                a.platform === "facebook" && fbStatus.data?.configured ? (
                  <button className="btn-primary h-8 px-3 text-xs" onClick={connectFacebookReal} disabled={connecting === "facebook"}>
                    {connecting === "facebook" ? <Spinner className="h-3.5 w-3.5" /> : null} Connect Facebook
                  </button>
                ) : (
                  <button className="btn-secondary h-8 px-3 text-xs" onClick={() => connectDemo(a.platform)} disabled={connecting === a.platform}>
                    {connecting === a.platform ? <Spinner className="h-3.5 w-3.5" /> : null} Connect (Demo)
                  </button>
                )
              ) : (
                <div className="flex gap-2">
                  {a.needs_reconnect && a.platform === "facebook" && fbStatus.data?.configured && (
                    <button className="btn-primary h-8 px-3 text-xs" onClick={connectFacebookReal} disabled={connecting === "facebook"}>
                      Reconnect
                    </button>
                  )}
                  <button className="btn-secondary h-8 px-3 text-xs text-rose-600 dark:text-rose-400" onClick={() => disconnect(a.platform)}>
                    Disconnect
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PagePicker({
  pages,
  pendingId,
  onSelected,
  onCancel,
}: {
  pages: any[];
  pendingId: string;
  onSelected: (pageId: string, pendingId: string) => void;
  onCancel: () => void;
}) {
  return (
    <div className="card border-2 border-brand-500 p-4">
      <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Choose a Facebook Page to connect</h3>
      <div className="mt-3 space-y-2">
        {pages.map((p) => (
          <button
            key={p.id}
            className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-left text-sm hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800/50"
            onClick={() => onSelected(p.id, pendingId)}
          >
            <span>{p.name}</span>
            {p.category && <span className="text-xs text-slate-400">{p.category}</span>}
          </button>
        ))}
      </div>
      <button className="btn-secondary mt-3 h-8 px-3 text-xs" onClick={onCancel}>Cancel</button>
    </div>
  );
}
