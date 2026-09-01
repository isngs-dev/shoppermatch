import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { AttributionBadge } from "../components/Attribution";
import { InvitationDrawer } from "../components/InvitationDrawer";
import { IconCursor, IconMail, IconSend, IconTarget, IconX } from "../components/Icons";
import { Badge, CopyButton, KpiCard, Loading, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
import { classNames, fmtDateTime, fmtMoney, statusBadgeClass } from "../lib/format";
import { useApi } from "../lib/useApi";

// --------------------------- Built-in templates --------------------------- //
const ASSIGNMENT_BUTTON =
  '<a href="{{assignment_link}}" style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;font-size:15px;font-weight:600;padding:14px 30px;border-radius:10px;">VIEW ASSIGNMENT</a>';

const VARIABLES = [
  ["shopper_name", "Shopper Name"],
  ["campaign_name", "Campaign Name"],
  ["client_name", "Client Name"],
  ["shop_name", "Shop Name"],
  ["location", "Location"],
  ["compensation", "Compensation"],
  ["deadline", "Deadline"],
  ["assignment_link", "Assignment Link"],
  ["invitation_id", "Invitation ID"],
] as const;

// Same branded markup as the backend's default template
// (backend/app/services/email.py::render_email) — a composed email never
// gets that wrapper automatically added at send time, so the only way the
// "before send" preview here and the "after send" preview in the invitation
// history actually match is for this compose default to contain the exact
// same branded HTML itself, not a bare-bones stand-in for it.
function builtinBody(badge: string, heading: string, intro: string) {
  return `\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;padding:24px 0;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e5e7eb;">
      <tr>
        <td style="background:#0f172a;padding:22px 32px;">
          <div style="color:#ffffff;font-size:18px;font-weight:700;letter-spacing:-0.2px;">ShopperMatch<span style="color:#6366f1;">.AI</span></div>
          <div style="color:#94a3b8;font-size:12px;margin-top:2px;">Delivered through ISN Shopper Recruitment</div>
        </td>
      </tr>
      <tr>
        <td style="padding:32px 32px 8px 32px;">
          <div style="display:inline-block;background:#eef2ff;color:#4f46e5;font-size:12px;font-weight:600;padding:5px 10px;border-radius:999px;">${badge}</div>
          <h1 style="font-size:22px;color:#0f172a;margin:16px 0 4px 0;">${heading}</h1>
          <p style="color:#475569;font-size:15px;line-height:1.6;margin:8px 0 0 0;">${intro}</p>
        </td>
      </tr>
      <tr>
        <td style="padding:20px 32px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;">
            <tr>
              <td style="padding:18px 20px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="padding:6px 0;color:#64748b;font-size:13px;width:40%;">Campaign</td>
                    <td style="padding:6px 0;color:#0f172a;font-size:14px;font-weight:600;">{{campaign_name}}</td>
                  </tr>
                  <tr>
                    <td style="padding:6px 0;color:#64748b;font-size:13px;">Shop</td>
                    <td style="padding:6px 0;color:#0f172a;font-size:14px;font-weight:600;">{{shop_name}}</td>
                  </tr>
                  <tr>
                    <td style="padding:6px 0;color:#64748b;font-size:13px;">Location</td>
                    <td style="padding:6px 0;color:#0f172a;font-size:14px;font-weight:600;">{{location}}</td>
                  </tr>
                  <tr>
                    <td style="padding:6px 0;color:#64748b;font-size:13px;">Compensation</td>
                    <td style="padding:6px 0;color:#16a34a;font-size:14px;font-weight:700;">{{compensation}}</td>
                  </tr>
                  <tr>
                    <td style="padding:6px 0;color:#64748b;font-size:13px;">Deadline</td>
                    <td style="padding:6px 0;color:#0f172a;font-size:14px;font-weight:600;">{{deadline}}</td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td align="center" style="padding:8px 32px 28px 32px;">
          ${ASSIGNMENT_BUTTON}
        </td>
      </tr>
      <tr>
        <td style="background:#f8fafc;border-top:1px solid #e5e7eb;padding:18px 32px;">
          <p style="color:#94a3b8;font-size:12px;line-height:1.6;margin:0;">
            You received this because you are an active shopper in the ShopperMatch.AI / ISN network. This is a synthetic demo message.
          </p>
        </td>
      </tr>
    </table>
  </td></tr>
</table>`;
}

type CampaignType = "active" | "upcoming";

// Upcoming campaigns haven't started — the default copy must not imply a
// current/active assignment (spec: "Do not make an upcoming campaign look
// like a completed/current assignment").
function builtinTemplates(campaignType: CampaignType): Record<string, { name: string; subject: string; body: string }> {
  const upcoming = campaignType === "upcoming";
  return {
    standard: {
      name: "Standard Invitation",
      subject: upcoming ? "Upcoming Mystery Shopping Opportunity — {{shop_name}}" : "Mystery Shopping Opportunity — {{shop_name}}",
      body: builtinBody(
        "Mystery Shopping Invitation",
        "Hi {{shopper_name}}, you've been selected 🎯",
        upcoming
          ? "You are invited to participate in an upcoming mystery shopping opportunity. Recruitment is open now so we can prepare your assignment ahead of the campaign start."
          : "Based on your profile and location, our matching engine selected you for a mystery shopping opportunity. Review the details below and let us know if you can take it."
      ),
    },
    urgent: {
      name: "Urgent Assignment",
      subject: upcoming ? "Reserve Your Spot — Upcoming Assignment — {{shop_name}}" : "Urgent: Mystery Shopper Needed — {{shop_name}}",
      body: builtinBody(
        "Urgent Opportunity",
        "Hi {{shopper_name}}, spots are filling fast ⚡",
        upcoming
          ? "This upcoming assignment is filling up fast — reserve your spot now ahead of the campaign start."
          : "We urgently need a shopper for this assignment — spots are limited and closing soon."
      ),
    },
    bonus: {
      name: "Bonus Opportunity",
      subject: "Bonus Opportunity — {{shop_name}}",
      body: builtinBody(
        "Bonus Included",
        "Hi {{shopper_name}}, this one comes with a bonus 💰",
        (upcoming ? "This upcoming assignment" : "This assignment") +
          " comes with a bonus incentive on top of standard compensation."
      ),
    },
    reminder: {
      name: "Reminder",
      subject: "Reminder — {{shop_name}}: your invitation is waiting",
      body: builtinBody(
        "Reminder",
        "Hi {{shopper_name}}, your invitation is still open ⏰",
        upcoming
          ? "Just a reminder that recruitment for this upcoming mystery shopping opportunity is still open."
          : "Just a reminder that this mystery shopping opportunity is still open for you."
      ),
    },
    followup: {
      name: "Follow-Up",
      subject: "Following up — {{shop_name}}",
      body: builtinBody(
        "Follow-Up",
        "Hi {{shopper_name}}, just following up 👋",
        "Following up on our earlier invitation in case it got buried in your inbox."
      ),
    },
    custom: {
      name: "Custom Email",
      subject: "",
      body: "<p>Hi {{shopper_name}},</p>\n<p></p>\n<p>Thank you,<br/>ISN Shopper Recruitment Team</p>",
    },
  };
}

type FocusTarget = "subject" | "body";

type ShopperOption = {
  id: string;
  name: string;
  city: string | null;
  availability_status: string | null;
  match_score: number | null;
  classification: string | null;
  // Only set in combined (multi-shop) mode — which shop this candidate was
  // recommended for, since a single composed send can now cover several.
  shopId?: string;
  shopName?: string;
  // Set when this shopper already has a real, created-but-unsent Invitation
  // (e.g. approved earlier in AI Recommendations) — sending them here reuses
  // that invitation via sendInvitation instead of creating a new one, so
  // approving in one place and sending from this checklist can never
  // double-invite the same shopper.
  pendingInvitationId?: string;
  pendingReference?: string;
};

// Template management lives on the Email Automation page (EmailTemplatesPanel,
// shared from pages/EmailTemplates.tsx), not here — templates are consumed by
// both manual sends and automation steps, so they don't belong to either
// exclusively. Email Automation also isn't a tab here: unlike Send Invitation
// it isn't scoped to one campaign (it runs across whichever campaign+shop you
// pick from its own selector), so it stays a separate top-level page.


export function Outreach() {
  const toast = useToast();
  const [searchParams] = useSearchParams();
  const preselectedCampaignId = searchParams.get("campaign") || "";
  const preselectedShopId = searchParams.get("shop") || "";

  // Active and Upcoming campaigns are fetched together and shown in one
  // list — no manual bucket toggle. Completed campaigns never appear here
  // (spec: don't mix campaign states; outreach is closed once completed).
  const activeCampaignsApi = useApi(() => api.campaigns({ status: "active" }));
  const upcomingCampaignsApi = useApi(() => api.campaigns({ status: "upcoming" }));
  const campaignsLoading =
    (activeCampaignsApi.loading && !activeCampaignsApi.data) || (upcomingCampaignsApi.loading && !upcomingCampaignsApi.data);
  const allCampaigns = useMemo(() => {
    const active = (activeCampaignsApi.data?.items || []).map((c: any) => ({ ...c, _bucket: "active" as const }));
    const upcoming = (upcomingCampaignsApi.data?.items || []).map((c: any) => ({ ...c, _bucket: "upcoming" as const }));
    return [...active, ...upcoming];
  }, [activeCampaignsApi.data, upcomingCampaignsApi.data]);
  const shoppers = useApi(() => api.shoppers());
  const templatesApi = useApi(() => api.emailTemplates());
  const settingsApi = useApi(() => api.settingsInfo());

  const [campaignId, setCampaignId] = useState("");
  // Multiple shops can be selected at once ("combined" mode) — `shopId`
  // stays as the single-shop derived value the rest of this component
  // (recs fetch, pending invitations fetch, draft preview) already assumes;
  // it's only meaningful when exactly one shop is checked.
  const [selectedShopIds, setSelectedShopIds] = useState<Set<string>>(new Set());
  const isMultiShop = selectedShopIds.size > 1;
  const shopId = selectedShopIds.size === 1 ? Array.from(selectedShopIds)[0] : "";
  const [shopperId, setShopperId] = useState("");
  const [recipientEmail, setRecipientEmail] = useState("");
  const [shops, setShops] = useState<any[]>([]);
  const [bonusShop, setBonusShop] = useState<any | null>(null);
  const [templateKey, setTemplateKey] = useState("standard");
  const [subject, setSubject] = useState(builtinTemplates("active").standard.subject);
  const [body, setBody] = useState(builtinTemplates("active").standard.body);

  // Lets the voice/chat assistant (mounted globally in ClientLayout, so it
  // has no direct access to this page's compose state) push a drafted email
  // into these exact fields when the client says "use this in outreach" —
  // decoupled via a plain window event rather than lifting subject/body into
  // shared state just for this one cross-component link.
  useEffect(() => {
    function onApplyDraft(e: Event) {
      const detail = (e as CustomEvent<{ subject: string; body: string }>).detail;
      if (!detail) return;
      setTemplateKey("custom");
      setSubject(detail.subject || "");
      setBody(
        (detail.body || "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/\n/g, "<br>")
      );
      toast("Applied the assistant's draft to this compose box.", "success");
    }
    window.addEventListener("sm:apply-email-draft", onApplyDraft);
    return () => window.removeEventListener("sm:apply-email-draft", onApplyDraft);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // AI-recommended candidates for the selected shop — this is what actually
  // populates the Shopper dropdown (spec: shoppers come from the existing
  // AI matching engine, not a flat unranked list).
  const recs = useApi(
    () => (shopId ? api.aiShopRecommendations(campaignId, shopId, { limit: 15 }) : Promise.resolve(null)),
    [shopId]
  );

  // Combined mode (multiple shops checked): reuses the same campaign-wide
  // AI Assignment Optimization the "Auto Assign Shoppers" card uses — one
  // shopper is never proposed for two shops in the same pass, and each
  // shop's own required_shoppers count is respected. Runs across the whole
  // campaign and gets filtered down to just the checked shops below, since
  // the optimizer has no "restrict to this subset" mode of its own.
  const combinedRecs = useApi(
    () => (isMultiShop ? api.aiOptimizeAssignments(campaignId) : Promise.resolve(null)),
    [campaignId, isMultiShop]
  );

  // Invitations already approved for this shop (e.g. via AI Recommendations)
  // but not yet emailed — folded into the checklist below instead of a
  // separate panel, so there's exactly one place to select/send shoppers.
  // Sending one of these reuses its existing Invitation (see sendBulk)
  // rather than creating a duplicate.
  const pendingInvitationsApi = useApi(
    () => (shopId ? api.invitations({ campaign_id: campaignId, shop_id: shopId, status: "created" }) : Promise.resolve({ items: [] })),
    [campaignId, shopId]
  );

  const [generating, setGenerating] = useState(false);
  const [generatingAi, setGeneratingAi] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  // The outbox worker delivers asynchronously (poll interval, not instant),
  // so `result.sent_at` can lag a few seconds behind a successful /send
  // call. This flips immediately on a successful send so the UI can't be
  // used to fire a second one while waiting for that to catch up — the
  // backend's sent_at guard (409) is the real protection either way.
  const [queuedLocally, setQueuedLocally] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [showSendConfirm, setShowSendConfirm] = useState(false);
  const [showTestBox, setShowTestBox] = useState(false);
  const [testEmail, setTestEmail] = useState("");
  const [showSaveTemplate, setShowSaveTemplate] = useState(false);
  const [newTemplateName, setNewTemplateName] = useState("");

  // ---- Recipient selection — a single always-on checklist. Selecting
  // exactly one shopper unlocks the single-recipient extras (AI
  // personalization, Send Test, live match-score breakdown) that only make
  // sense for one person; selecting several sends the same composed email
  // to all of them via the batched bulk path. No separate mode toggle. ---- //
  const emailStatus = useApi(() => api.clientEmailStatus());
  const [bulkSelected, setBulkSelected] = useState<Set<string>>(new Set());
  const singleMode = bulkSelected.size === 1;
  const [bulkSending, setBulkSending] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ batch: number; totalBatches: number } | null>(null);
  const [bulkResult, setBulkResult] = useState<{ created: any[]; failed: any[] } | null>(null);

  const subjectRef = useRef<HTMLInputElement>(null);
  const bodyEditableRef = useRef<HTMLDivElement | null>(null);
  const savedBodyRangeRef = useRef<Range | null>(null);
  const lastFocused = useRef<FocusTarget>("body");

  // The body editor is a rendered, editable preview (contentEditable), not a
  // raw-HTML textarea — the client sees/edits the email the way it will
  // actually look, per spec. Kept uncontrolled on every render (no
  // dangerouslySetInnerHTML) so typing never fights React for the cursor;
  // this effect only pushes `body` into the DOM when it changed from
  // somewhere else (template switch, AI generation, variable insertion).
  useEffect(() => {
    const el = bodyEditableRef.current;
    if (el && el.innerHTML !== body) {
      el.innerHTML = body;
    }
  }, [body]);

  // Covers the case where the editable div mounts (or remounts, e.g. a tab
  // switch) *after* `body` already holds its current value — the effect
  // above only re-runs on a `body` change, so without this the freshly
  // mounted div would stay empty until the next edit.
  const bodyValueRef = useRef(body);
  bodyValueRef.current = body;
  const bodyCallbackRef = (el: HTMLDivElement | null) => {
    bodyEditableRef.current = el;
    if (el && el.innerHTML !== bodyValueRef.current) {
      el.innerHTML = bodyValueRef.current;
    }
  };

  function handleBodyInput(e: React.FormEvent<HTMLDivElement>) {
    setBody(e.currentTarget.innerHTML);
  }

  function handleBodyBlur() {
    const sel = window.getSelection();
    if (sel && sel.rangeCount > 0 && bodyEditableRef.current?.contains(sel.anchorNode)) {
      savedBodyRangeRef.current = sel.getRangeAt(0).cloneRange();
    }
  }

  // The campaign's bucket (active/upcoming) is derived from whichever
  // campaign is currently selected — there's no manual toggle anymore.
  const selectedCampaignMeta = allCampaigns.find((c) => c.id === campaignId);
  const campaignType: CampaignType = selectedCampaignMeta?._bucket === "upcoming" ? "upcoming" : "active";

  // Keep campaignId valid for whatever's currently loaded, preferring a
  // `?campaign=` deep link (e.g. from "Approve & Go to Outreach") over just
  // picking the first campaign.
  useEffect(() => {
    if (!allCampaigns.length) {
      if (campaignId) setCampaignId("");
      return;
    }
    if (allCampaigns.some((c) => c.id === campaignId)) return;
    const preselected = preselectedCampaignId ? allCampaigns.find((c) => c.id === preselectedCampaignId) : null;
    setCampaignId(preselected?.id || allCampaigns[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allCampaigns]);

  useEffect(() => {
    if (!campaignId) return;
    api.campaignShops(campaignId).then((r) => {
      setShops(r.items);
      const preferred = preselectedShopId && r.items.some((s: any) => s.id === preselectedShopId);
      const initial = preferred ? preselectedShopId : r.items[0]?.id;
      setSelectedShopIds(initial ? new Set([initial]) : new Set());
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignId]);

  // Refreshes just the shop list (bonus badges etc.) without resetting the
  // current shop selection — used after adding/removing a bonus.
  function reloadShops() {
    if (!campaignId) return;
    api.campaignShops(campaignId).then((r) => setShops(r.items));
  }

  // Force a fresh top-candidate pick whenever the shop changes (campaign
  // switch or a direct dropdown pick) — otherwise a shopper who's merely a
  // *valid* low-score candidate for the new shop (e.g. carried over from
  // the pre-AI fallback list) would never be replaced by the actual top
  // AI match once recommendations for the new shop finish loading.
  useEffect(() => {
    setShopperId("");
    setBulkSelected(new Set());
    setBulkResult(null);
  }, [selectedShopIds]);

  // Drives the single-recipient extras (AI personalization, Send Test,
  // breakdown) off whichever shopper is selected — `shopperId` only ever
  // matters when exactly one checkbox is checked.
  useEffect(() => {
    if (bulkSelected.size === 1) {
      setShopperId(Array.from(bulkSelected)[0]);
    } else if (shopperId) {
      setShopperId("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bulkSelected]);

  function toggleBulkSelected(id: string) {
    setBulkSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const maxBatchSize = emailStatus.data?.bulk_email_batch_size ?? 1000;
  const bulkSelectedIds = Array.from(bulkSelected);
  // Every selected shopper is sent — batching by maxBatchSize below is purely
  // an internal chunking detail (the backend's per-call limit), never a cap
  // the client has to configure.
  const bulkWillSendCount = bulkSelectedIds.length;

  async function sendBulk() {
    if (!campaignId || (!shopId && !isMultiShop) || bulkSelectedIds.length === 0) {
      toast("Select at least one shopper first.", "error");
      return;
    }
    if (!subject.trim() || !body.trim()) {
      toast("Subject and body cannot be empty.", "error");
      return;
    }
    const targets = bulkSelectedIds.slice(0, bulkWillSendCount);

    // Anyone already approved earlier (a real, created-but-unsent
    // Invitation) reuses that exact invitation via sendInvitation — never
    // recreated — so approving in AI Recommendations and sending from this
    // checklist can never double-invite the same shopper. Only shoppers
    // with no existing invitation go through the create-and-send path below.
    const alreadyPending = targets.filter((id) => pendingByShopperId.has(id));
    const freshTargets = targets.filter((id) => !pendingByShopperId.has(id));

    // Combined mode spans several shops in one send — group targets by
    // their proposed shop first (createBulkInvitations takes one shop_id
    // per call), then chunk each shop's group by batchSize same as before.
    // Single-shop mode is just one group, same behavior as always.
    const groups: { shopId: string; shopperIds: string[] }[] = isMultiShop
      ? Array.from(
          freshTargets.reduce((byShop, id) => {
            const sid = shopperShopMap.get(id);
            if (!sid) return byShop;
            byShop.set(sid, [...(byShop.get(sid) || []), id]);
            return byShop;
          }, new Map<string, string[]>())
        ).map(([sid, ids]) => ({ shopId: sid, shopperIds: ids }))
      : [{ shopId, shopperIds: freshTargets }];

    const batches: { shopId: string; shopperIds: string[] }[] = [];
    for (const g of groups) {
      for (let i = 0; i < g.shopperIds.length; i += maxBatchSize) {
        batches.push({ shopId: g.shopId, shopperIds: g.shopperIds.slice(i, i + maxBatchSize) });
      }
    }

    setBulkSending(true);
    setBulkResult(null);
    const created: any[] = [];
    const failed: any[] = [];
    const totalSteps = alreadyPending.length + batches.length;
    let step = 0;

    for (const id of alreadyPending) {
      step += 1;
      setBulkProgress({ batch: step, totalBatches: totalSteps });
      const pending = pendingByShopperId.get(id)!;
      try {
        await api.sendInvitation(pending.id, subject, body);
        created.push({ shopper_id: id, invitation_id: pending.id, reference: pending.reference });
      } catch (e: any) {
        failed.push({ shopper_id: id, error: e?.message || "Failed to send" });
      }
    }

    // Each batch is caught individually — combined mode can span several
    // shops in one send, and one shop's over-selection guard (or any other
    // per-shop rejection) rejecting its batch must not throw away results
    // already created for a different shop earlier in the same loop.
    for (let i = 0; i < batches.length; i++) {
      step += 1;
      setBulkProgress({ batch: step, totalBatches: totalSteps });
      try {
        const res = await api.createBulkInvitations({
          campaign_id: campaignId,
          shop_id: batches[i].shopId,
          shopper_ids: batches[i].shopperIds,
          auto_send: true,
          custom_subject: subject,
          custom_html: body,
        });
        created.push(...res.created);
        failed.push(...res.failed);
      } catch (e: any) {
        const shopName = shops.find((s: any) => s.id === batches[i].shopId)?.shop_name || batches[i].shopId;
        failed.push(
          ...batches[i].shopperIds.map((id) => ({
            shopper_id: id,
            error: e?.message || `Failed for ${shopName}`,
          }))
        );
      }
    }
    setBulkResult({ created, failed });
    toast(`Bulk send queued: ${created.length} invitation(s) sent${failed.length ? `, ${failed.length} failed` : ""}.`, failed.length ? "info" : "success");
    setBulkSending(false);
    setBulkProgress(null);
    pendingInvitationsApi.reload();
  }

  // Candidates come from the AI matching engine for the selected shop —
  // not a flat, unranked shopper list. `shoppers.data` (fetched once, full
  // roster) is kept only as an email lookup and as a fallback while
  // recommendations are loading or if a shop has none.
  // Invitations already approved for this shop but not yet emailed, keyed
  // by shopper id — used to (a) tag a candidate already in the AI list as
  // "already approved" and (b) add anyone approved earlier who has since
  // fallen out of the AI's top-N ranking, so nobody with a real pending
  // invitation is ever left invisible/unsendable from this checklist.
  const pendingByShopperId = useMemo(() => {
    const map = new Map<string, { id: string; reference: string }>();
    for (const inv of (pendingInvitationsApi.data?.items || []) as any[]) {
      if (inv.shopper_id) map.set(inv.shopper_id, { id: inv.id, reference: inv.reference });
    }
    return map;
  }, [pendingInvitationsApi.data]);

  const shopperOptions = useMemo((): ShopperOption[] => {
    if (isMultiShop) {
      const proposals = (combinedRecs.data?.proposals || []) as any[];
      return proposals
        .filter((p) => selectedShopIds.has(p.shop_id))
        .map(
          (p): ShopperOption => ({
            id: p.shopper_id,
            name: p.shopper_name,
            city: null,
            availability_status: null,
            match_score: p.match_score ?? null,
            classification: null,
            shopId: p.shop_id,
            shopName: p.shop_name,
          })
        );
    }

    const withPending = (list: ShopperOption[]): ShopperOption[] => {
      const seen = new Set(list.map((o) => o.id));
      const merged = list.map((o) => {
        const pending = pendingByShopperId.get(o.id);
        return pending ? { ...o, pendingInvitationId: pending.id, pendingReference: pending.reference } : o;
      });
      for (const inv of (pendingInvitationsApi.data?.items || []) as any[]) {
        if (!inv.shopper_id || seen.has(inv.shopper_id)) continue;
        merged.push({
          id: inv.shopper_id,
          name: inv.shopper_name || inv.shopper_email,
          city: null,
          availability_status: null,
          match_score: null,
          classification: null,
          pendingInvitationId: inv.id,
          pendingReference: inv.reference,
        });
        seen.add(inv.shopper_id);
      }
      return merged;
    };

    const candidates = recs.data?.recommendations || [];
    if (candidates.length) {
      return withPending(
        candidates.map(
          (r: any): ShopperOption => ({
            id: r.shopper_id,
            name: r.name,
            city: r.city,
            availability_status: r.availability,
            match_score: r.match_score ?? null,
            classification: r.classification ?? null,
          })
        )
      );
    }
    return withPending(
      (shoppers.data?.items || []).map(
        (s: any): ShopperOption => ({
          id: s.id,
          name: s.name,
          city: s.city,
          availability_status: s.availability_status,
          match_score: null,
          classification: null,
        })
      )
    );
  }, [isMultiShop, combinedRecs.data, selectedShopIds, recs.data, shoppers.data, pendingByShopperId, pendingInvitationsApi.data]);

  // Maps a selected shopper back to which shop they were recommended for —
  // only meaningful/populated in combined mode, used by sendBulk to route
  // each shopper's invitation to the right shop.
  const shopperShopMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const o of shopperOptions) {
      if (o.shopId) map.set(o.id, o.shopId);
    }
    return map;
  }, [shopperOptions]);

  useEffect(() => {
    if (!shopperOptions.length) return;
    if (!shopperOptions.some((o) => o.id === shopperId)) {
      setShopperId(shopperOptions[0].id);
    }
  }, [shopperOptions]);

  // Auto-fulfill the selected shop's requirement: pre-select exactly its
  // required_shoppers count from the top of the ranked candidate list
  // (already sorted best-match-first by the matching engine), instead of
  // starting empty and making the client manually pick every time they
  // switch shops. Keyed on recs.data (not shopperOptions, which is a new
  // array reference every render) so this only fires once per actual shop
  // change, not on every re-render — "Select all"/"Clear" below still
  // override it manually whenever needed.
  useEffect(() => {
    if (!shopperOptions.length) return;
    if (isMultiShop) {
      // The optimizer already returned exactly the right set — one
      // proposal per shop's requirement, no shopper double-booked across
      // shops — so select all of it rather than re-slicing by count.
      setBulkSelected(new Set(shopperOptions.map((s) => s.id)));
      return;
    }
    // Anyone already approved (a real pending invitation) is always
    // pre-selected — they were ready to send before this checklist even
    // loaded — on top of the usual top-N fresh AI picks.
    const pendingIds = shopperOptions.filter((s) => s.pendingInvitationId).map((s) => s.id);
    const required = shops.find((s: any) => s.id === shopId)?.required_shoppers || 0;
    const topPicks = required > 0 ? shopperOptions.slice(0, required).map((s) => s.id) : [];
    setBulkSelected(new Set([...topPicks, ...pendingIds]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recs.data, combinedRecs.data, pendingInvitationsApi.data]);

  const selectedShopper = useMemo(
    () => shopperOptions.find((s) => s.id === shopperId),
    [shopperOptions, shopperId]
  );

  // ---- Live draft preview (shown before an invitation is generated) ---- //
  // No real tracking token exists yet at this point, so this substitutes
  // every variable we DO already know (campaign/shop/shopper) and renders
  // it exactly like the real preview — the client sees precisely what will
  // go out before committing to Generate/Send, and can keep editing.
  const draftCampaign = allCampaigns.find((c) => c.id === campaignId);
  const firstSelectedShopper = shopperOptions.find((o) => o.id === Array.from(bulkSelected)[0]);
  // In combined mode there's no single selected shop — fall back to
  // whichever shop the first selected shopper was actually proposed for,
  // so the draft preview shows real data instead of going blank.
  const draftShop = shops.find((s) => s.id === (shopId || firstSelectedShopper?.shopId));
  const draftShopperName = firstSelectedShopper?.name;
  const draftContext = useMemo(() => {
    const location = [draftShop?.city, draftShop?.state].filter(Boolean).join(", ");
    return {
      shopper_name: draftShopperName?.split(" ")[0] || draftShopperName || "there",
      campaign_name: draftCampaign?.name || "",
      client_name: draftCampaign?.client_name || "",
      shop_name: draftShop?.shop_name || "",
      location,
      compensation: draftShop?.compensation != null ? `${draftShop.currency || "INR"} ${draftShop.compensation}` : "",
      deadline: draftShop?.visit_end ? fmtDateTime(draftShop.visit_end) : "",
      assignment_link: "#",
      invitation_id: "(assigned once sent)",
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftCampaign, draftShop, draftShopperName]);

  // Always fetch the definitive shopper record for the recipient email —
  // the flat `shoppers.data` list can be paginated/stale and miss whichever
  // shopper the AI just recommended, silently leaving Recipient blank.
  useEffect(() => {
    if (!shopperId) {
      setRecipientEmail("");
      return;
    }
    let cancelled = false;
    api.shopper(shopperId).then((s) => {
      if (!cancelled) setRecipientEmail(s?.email || "");
    });
    return () => {
      cancelled = true;
    };
  }, [shopperId]);

  // New selection target invalidates any in-progress draft (matches spec:
  // switching campaign/shop/shopper starts a fresh invitation).
  useEffect(() => {
    setResult(null);
    setQueuedLocally(false);
  }, [campaignId, shopId, shopperId]);

  const savedTemplates: any[] = templatesApi.data?.items || [];

  function applyTemplate(key: string) {
    setTemplateKey(key);
    if (key.startsWith("saved:")) {
      const t = savedTemplates.find((x) => x.id === key.slice(6));
      if (t) {
        setSubject(t.subject);
        setBody(t.html_body);
      }
      return;
    }
    const bt = builtinTemplates(campaignType)[key];
    if (bt) {
      setSubject(bt.subject);
      setBody(bt.body);
    }
  }

  // Re-apply the active built-in template's copy when campaign type flips,
  // so "upcoming" vs "active" phrasing (see builtinTemplates) takes effect
  // without discarding a saved/custom draft the admin is editing.
  useEffect(() => {
    if (templateKey === "custom" || templateKey.startsWith("saved:")) return;
    const bt = builtinTemplates(campaignType)[templateKey];
    if (bt) {
      setSubject(bt.subject);
      setBody(bt.body);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignType]);

  function insertAtCursor(text: string) {
    const target = lastFocused.current;
    if (target === "subject" && subjectRef.current) {
      const el = subjectRef.current;
      const start = el.selectionStart ?? subject.length;
      const end = el.selectionEnd ?? subject.length;
      const next = subject.slice(0, start) + text + subject.slice(end);
      setSubject(next);
      requestAnimationFrame(() => el.setSelectionRange(start + text.length, start + text.length));
    } else if (bodyEditableRef.current) {
      const el = bodyEditableRef.current;
      const sel = window.getSelection();
      // If the live selection is still inside the body (focus never actually
      // left it), leave it alone — only when focus has genuinely moved away
      // (the normal case: clicking a toolbar button blurs the body first) do
      // we need to restore the cursor position from before that blur.
      const liveSelectionInBody =
        sel && sel.rangeCount > 0 && el.contains(sel.getRangeAt(0).commonAncestorContainer);
      if (!liveSelectionInBody) {
        el.focus();
        if (sel) {
          sel.removeAllRanges();
          if (savedBodyRangeRef.current && el.contains(savedBodyRangeRef.current.startContainer)) {
            sel.addRange(savedBodyRangeRef.current);
          } else {
            // No prior cursor position in the body (e.g. never focused it yet) — insert at the end.
            const r = document.createRange();
            r.selectNodeContents(el);
            r.collapse(false);
            sel.addRange(r);
          }
        }
      }
      document.execCommand("insertHTML", false, text);
      savedBodyRangeRef.current = window.getSelection()?.rangeCount ? window.getSelection()!.getRangeAt(0).cloneRange() : null;
      setBody(el.innerHTML);
    }
  }

  async function saveTemplate() {
    if (!newTemplateName.trim()) return;
    try {
      await api.createEmailTemplate({ name: newTemplateName.trim(), subject, html_body: body });
      toast(`Template "${newTemplateName.trim()}" saved.`, "success");
      setShowSaveTemplate(false);
      setNewTemplateName("");
      templatesApi.reload();
    } catch (e: any) {
      toast(e?.message || "Failed to save template", "error");
    }
  }

  async function generateWithAi() {
    if (!campaignId || !shopId || !shopperId) return;
    setGeneratingAi(true);
    try {
      const res = await api.aiPersonalizeEmail(campaignId, shopId, shopperId);
      setSubject(res.subject);
      setBody(res.body);
      setTemplateKey("custom");
      toast("AI-personalized draft loaded — review and edit before sending.", "success");
    } catch (e: any) {
      toast(e?.message || "Failed to generate with AI", "error");
    } finally {
      setGeneratingAi(false);
    }
  }

  async function generate() {
    if (!campaignId || !shopId || !shopperId) {
      toast("Select a campaign, shop and shopper first.", "error");
      return;
    }
    if (!recipientEmail.trim()) {
      toast("Enter the recipient email address first.", "error");
      return;
    }
    if (!subject.trim() || !body.trim()) {
      toast("Subject and body cannot be empty.", "error");
      return;
    }
    setGenerating(true);
    setResult(null);
    setQueuedLocally(false);
    try {
      // Already approved (e.g. from AI Recommendations) — reuse that exact
      // invitation instead of creating a duplicate for the same shopper.
      const pending = selectedShopper?.pendingInvitationId;
      const inv = pending
        ? await api.invitation(pending)
        : await api.createInvitation({
            campaign_id: campaignId,
            shop_id: shopId,
            shopper_id: shopperId,
            recipient_email: recipientEmail.trim(),
            auto_send: false,
            custom_subject: subject,
            custom_html: body,
          });
      setResult(inv);
      toast(
        pending
          ? `Invitation ${inv.reference} was already approved. Preview it, then Send Email.`
          : `Invitation ${inv.reference} generated. Preview it, then Send Email.`,
        "success"
      );
    } catch (e: any) {
      toast(e?.message || "Failed to generate invitation", "error");
    } finally {
      setGenerating(false);
    }
  }

  async function doSend() {
    if (!result) return;
    setBusy("send");
    setShowSendConfirm(false);
    try {
      const res = await api.sendInvitation(result.id);
      setQueuedLocally(true);
      toast(`Queued for delivery via ${res.provider}.`, "success");
      const fresh = await api.invitation(result.id);
      setResult((prev: any) => ({ ...prev, ...fresh }));
    } catch (e: any) {
      toast(e?.message || "Failed to send", "error");
    } finally {
      setBusy(null);
    }
  }

  async function doSendTest() {
    if (!result || !testEmail.trim()) return;
    setBusy("test");
    try {
      const res = await api.sendTestInvitation(result.id, testEmail.trim());
      if (res.provider_result?.delivered) {
        toast(`Test email sent to ${testEmail.trim()} via ${res.provider_result.provider}.`, "success");
      } else {
        toast(`Test send failed: ${res.provider_result?.detail || "unknown error"}`, "error");
      }
    } catch (e: any) {
      toast(e?.message || "Failed to send test email", "error");
    } finally {
      setBusy(null);
    }
  }

  async function doFollowUp() {
    if (!result) return;
    setBusy("followup");
    try {
      const inv = await api.followUpInvitation(result.id);
      setResult(inv);
      setQueuedLocally(false);
      toast(`Follow-up ${inv.reference} generated. Preview and send it separately.`, "success");
    } catch (e: any) {
      toast(e?.message || "Failed to create follow-up", "error");
    } finally {
      setBusy(null);
    }
  }

  async function simulate(action: string, label: string) {
    if (!result) return;
    setBusy(action);
    try {
      const updated = await api.simulate(result.id, action);
      setResult(updated);
      toast(
        updated.simulation?.newly_recorded === false
          ? `${label}: already recorded.`
          : `SIMULATED — ${label} recorded in database.`,
        "info"
      );
    } catch (e: any) {
      toast(e?.message || "Simulation failed", "error");
    } finally {
      setBusy(null);
    }
  }

  if (shoppers.loading && !shoppers.data) return <Loading label="Loading outreach…" />;

  const fromDisplay = settingsApi.data
    ? `${settingsApi.data.email_from}`
    : "ISN Shopper Recruitment";
  const emailNotConfigured = settingsApi.data?.email_provider === "mock";
  const alreadySent = !!result?.sent_at || queuedLocally;
  const canSend = !!result && !alreadySent && !!subject.trim() && !!body.trim() && !!recipientEmail.trim();
  const previewHtml = result?.email_preview?.html || "";
  const previewSubject = result?.email_preview?.subject || subject;

  function renderDraftVariables(template: string): string {
    return template.replace(/\{\{\s*([a-zA-Z_]+)\s*\}\}/g, (match, key) => {
      const value = (draftContext as Record<string, string>)[key.trim()];
      return value !== undefined && value !== "" ? value : match;
    });
  }

  const draftSubject = renderDraftVariables(subject);
  const draftBodyDoc =
    `<!DOCTYPE html><html><head><meta charset="utf-8" /></head>` +
    `<body style="margin:0;padding:16px;background:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.6;color:#1e293b;">` +
    renderDraftVariables(body) +
    `</body></html><style>a{pointer-events:none!important;cursor:default!important;}</style>`;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900 dark:text-white">Outreach</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Send invitations to AI-recommended shoppers and track responses in real time.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Left: selectors + composer */}
        <div className="space-y-4 lg:col-span-2">
          <div className="card p-5">
            <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Compose</h2>

            {campaignType === "upcoming" && (
              <p className="mt-2 rounded-lg bg-violet-50 px-3 py-2 text-[11px] font-medium text-violet-700 dark:bg-violet-950/40 dark:text-violet-300">
                UPCOMING CAMPAIGN — this is recruitment / invitation preparation, not an active assignment.
              </p>
            )}

            <div className="mt-4 space-y-4">
              <div>
                <label className="label">Campaign</label>
                {campaignsLoading ? (
                  <div className="input flex items-center text-sm text-slate-400">
                    <Spinner className="mr-2 h-4 w-4" /> Loading campaigns…
                  </div>
                ) : !allCampaigns.length ? (
                  <div className="input flex items-center text-sm text-slate-400">
                    No active or upcoming campaigns available.
                  </div>
                ) : (
                  <select className="input" value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
                    {allCampaigns.map((c: any) => (
                      <option key={c.id} value={c.id}>
                        {c.name} {c._bucket === "upcoming" ? "(Upcoming)" : ""}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div>
                <div className="flex items-center justify-between">
                  <label className="label !mb-0">
                    Shop{isMultiShop ? ` — ${selectedShopIds.size} selected, combined requirement` : ""}
                  </label>
                  {shops.length > 1 && (
                    <div className="flex gap-2 text-[11px]">
                      <button
                        type="button"
                        className="font-semibold text-brand-600 hover:underline dark:text-brand-400"
                        onClick={() => setSelectedShopIds(new Set(shops.map((s: any) => s.id)))}
                      >
                        Select all
                      </button>
                      <button
                        type="button"
                        className="font-semibold text-slate-400 hover:underline"
                        onClick={() => setSelectedShopIds(new Set())}
                      >
                        Deselect all
                      </button>
                    </div>
                  )}
                </div>
                {campaignId && !shops.length ? (
                  <div className="input mt-1.5 flex items-center text-sm text-slate-400">
                    <Spinner className="mr-2 h-4 w-4" /> Loading shops…
                  </div>
                ) : (
                  <div className="mt-1.5 max-h-40 space-y-1 overflow-y-auto rounded-lg border border-slate-200 p-2 dark:border-slate-700">
                    {shops.map((s: any) => (
                      <label
                        key={s.id}
                        className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50"
                      >
                        <input
                          type="checkbox"
                          checked={selectedShopIds.has(s.id)}
                          onChange={() =>
                            setSelectedShopIds((prev) => {
                              const next = new Set(prev);
                              if (next.has(s.id)) next.delete(s.id);
                              else next.add(s.id);
                              return next;
                            })
                          }
                        />
                        <span className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-200">
                          {s.shop_name} — {s.city}
                        </span>
                        <span className="shrink-0 text-xs text-slate-400">requires {s.required_shoppers}</span>
                        <button
                          type="button"
                          className={classNames(
                            "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold",
                            s.bonus
                              ? "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                              : "bg-slate-100 text-slate-500 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700"
                          )}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setBonusShop(s);
                          }}
                        >
                          {s.bonus
                            ? `💰 ${fmtMoney(s.bonus.amount, s.bonus.currency)}${s.bonus.completed_at ? " · Paid" : ""}`
                            : "+ Bonus"}
                        </button>
                      </label>
                    ))}
                  </div>
                )}
                {isMultiShop && (
                  <p className="mt-1 text-[11px] text-slate-400">
                    AI Recommendations below combines all {selectedShopIds.size} shops — the same shopper is never
                    proposed for two of them, and each shop's own required count is respected.
                  </p>
                )}
              </div>

              <div>
                <label className="label">
                  Shopper(s) {campaignType === "upcoming" ? "(recommended candidates)" : "(AI recommended)"} —{" "}
                  {bulkSelected.size} selected
                </label>
                {(shopId && recs.loading && !recs.data) || (isMultiShop && combinedRecs.loading && !combinedRecs.data) ? (
                  <div className="input flex items-center text-sm text-slate-400">
                    <Spinner className="mr-2 h-4 w-4" /> AI is matching shoppers…
                  </div>
                ) : !shopperOptions.length ? (
                  <div className="input flex items-center text-sm text-slate-400">Finding eligible shoppers…</div>
                ) : (
                  <>
                    <div className="flex gap-2 pb-1.5 text-[11px]">
                      <button
                        type="button"
                        className="font-semibold text-brand-600 hover:underline dark:text-brand-400"
                        onClick={() => setBulkSelected(new Set(shopperOptions.map((s) => s.id)))}
                      >
                        Select all
                      </button>
                      <button
                        type="button"
                        className="font-semibold text-slate-400 hover:underline"
                        onClick={() => setBulkSelected(new Set())}
                      >
                        Deselect all
                      </button>
                    </div>
                    <div className="max-h-56 space-y-1 overflow-y-auto rounded-lg border border-slate-200 p-2 dark:border-slate-700">
                      {shopperOptions.map((s) => (
                        <label
                          key={s.id}
                          className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50"
                        >
                          <input type="checkbox" checked={bulkSelected.has(s.id)} onChange={() => toggleBulkSelected(s.id)} />
                          <span className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-200">
                            {s.shopName
                              ? `${s.name} — for ${s.shopName}`
                              : s.city
                              ? `${s.name} — ${s.city} (${s.availability_status})`
                              : s.name}
                          </span>
                          {s.pendingInvitationId ? (
                            <span
                              className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-950/50 dark:text-amber-300"
                              title="Already approved in AI Recommendations — sending reuses this invitation"
                            >
                              Approved · {s.pendingReference}
                            </span>
                          ) : (
                            s.match_score != null && (
                              <span className="shrink-0 text-xs font-semibold text-brand-600 dark:text-brand-400">{s.match_score}%</span>
                            )
                          )}
                        </label>
                      ))}
                    </div>
                  </>
                )}
              </div>

              {singleMode && (
                <>
                  {selectedShopper?.match_score != null && (
                    <p className="-mt-2 text-[11px] text-slate-400">
                      AI match: <span className="font-semibold text-brand-600 dark:text-brand-400">{selectedShopper.match_score}%</span>
                      {selectedShopper.classification ? ` · ${selectedShopper.classification.replace("_", " ")}` : ""}
                    </p>
                  )}
                  <div>
                    <label className="label">Recipient</label>
                    <input
                      className="input"
                      type="email"
                      value={recipientEmail}
                      onChange={(e) => setRecipientEmail(e.target.value)}
                      placeholder="shopper@example.com"
                    />
                    <p className="mt-1 text-[11px] text-slate-400">
                      Auto-filled from the selected shopper; editable for this invitation only.
                    </p>
                  </div>
                </>
              )}

              <div>
                <label className="label">Template</label>
                <select className="input" value={templateKey} onChange={(e) => applyTemplate(e.target.value)}>
                  <optgroup label="Built-in">
                    {Object.entries(builtinTemplates(campaignType)).map(([key, t]) => (
                      <option key={key} value={key}>
                        {t.name}
                      </option>
                    ))}
                  </optgroup>
                  {savedTemplates.length > 0 && (
                    <optgroup label="Saved templates">
                      {savedTemplates.map((t) => (
                        <option key={t.id} value={`saved:${t.id}`}>
                          {t.name}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
              </div>
            </div>
          </div>

        </div>

        {/* Right: composer + preview + tracking + send — kept together so
            editing and its live preview always sit side by side, one glance
            apart, instead of the editor being on the opposite side of the
            screen from the preview it controls. */}
        <div className="space-y-4 lg:col-span-3">
          <div className="card p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Compose Email</h2>
              <span className="text-[11px] text-slate-400">Edit freely before sending</span>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
              <div>
                <div className="text-slate-400">From</div>
                <div className="truncate font-medium text-slate-700 dark:text-slate-200">{fromDisplay}</div>
              </div>
              <div>
                <div className="text-slate-400">To</div>
                <div className="truncate font-medium text-slate-700 dark:text-slate-200">
                  {singleMode ? recipientEmail || "—" : `${bulkSelected.size} shopper(s) selected`}
                </div>
              </div>
            </div>

            <div className="mt-4">
              <label className="label">Subject</label>
              <input
                ref={subjectRef}
                className="input"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                onFocus={() => (lastFocused.current = "subject")}
              />
            </div>

            <div className="mt-3">
              <label className="label">Email Body</label>
              <p className="mb-1.5 text-[11px] text-slate-400">
                This is a live preview of the email — click into it and edit the text directly, just like the shopper will read it.
              </p>
              <div
                ref={bodyCallbackRef}
                contentEditable
                suppressContentEditableWarning
                onInput={handleBodyInput}
                onFocus={() => (lastFocused.current = "body")}
                onBlur={handleBodyBlur}
                className="min-h-[224px] resize-y overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 text-sm leading-relaxed text-slate-800 shadow-inner focus:outline-none focus:ring-2 focus:ring-brand-500"
                style={{ fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif" }}
              />
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <select
                className="input h-9 w-44"
                value=""
                onChange={(e) => {
                  if (e.target.value) insertAtCursor(`{{${e.target.value}}}`);
                  e.target.value = "";
                }}
              >
                <option value="">Insert Variable ▾</option>
                {VARIABLES.map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
              <button className="btn-secondary h-9" onClick={() => insertAtCursor(ASSIGNMENT_BUTTON)}>
                Insert Assignment Button
              </button>
              <button className="btn-secondary h-9" onClick={() => setShowSaveTemplate(true)}>
                Save as Template
              </button>
              {singleMode && (
                <button className="btn-secondary h-9" onClick={generateWithAi} disabled={generatingAi || !campaignId || !shopId || !shopperId}>
                  {generatingAi ? <Spinner /> : null} ✨ Generate with AI
                </button>
              )}
            </div>

            {bulkSelected.size === 0 ? (
              <button className="btn-primary mt-4 w-full py-2.5" disabled>
                Select at least one shopper above
              </button>
            ) : singleMode ? (
              <button className="btn-primary mt-4 w-full py-2.5" onClick={generate} disabled={generating}>
                {generating ? <Spinner /> : <><IconSend width={16} height={16} /> Generate Invitation</>}
              </button>
            ) : (
              <button className="btn-primary mt-4 w-full py-2.5" onClick={sendBulk} disabled={bulkSending}>
                {bulkSending ? (
                  <>
                    <Spinner /> Sending batch {bulkProgress?.batch ?? 1} of {bulkProgress?.totalBatches ?? 1}…
                  </>
                ) : (
                  <><IconSend width={16} height={16} /> Send Bulk Invitations ({bulkWillSendCount})</>
                )}
              </button>
            )}
          </div>

          {!singleMode ? (
            <BulkResultPanel
              result={bulkResult}
              sending={bulkSending}
              draftSubject={draftSubject}
              draftBodyDoc={draftBodyDoc}
              recipientCount={bulkSelected.size}
            />
          ) : !result ? (
            <div className="card overflow-hidden">
              <div className="border-b border-slate-200 bg-amber-50 p-4 dark:border-slate-800 dark:bg-amber-950/30">
                <div className="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
                  Draft preview — not sent yet
                </div>
                <div className="mt-0.5 text-xs text-amber-700/80 dark:text-amber-400/80">
                  This is exactly what {draftShopperName || "the shopper"} will receive. Keep editing above, then
                  click <span className="font-semibold">Generate Invitation</span> when it's ready to send.
                </div>
              </div>
              <div className="border-b border-slate-200 p-3 dark:border-slate-800">
                <div className="text-xs text-slate-400">Subject (rendered)</div>
                <div className="text-sm font-semibold text-slate-900 dark:text-white">{draftSubject}</div>
              </div>
              <iframe title="Draft email preview" srcDoc={draftBodyDoc} sandbox="" className="h-[420px] w-full border-0 bg-white" />
            </div>
          ) : (
            <div className="space-y-4">
              <div className="card p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                      Generated invitation
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-lg font-bold text-slate-900 dark:text-white">{result.reference}</span>
                      <Badge className={statusBadgeClass(result.status)}>{result.status}</Badge>
                      {result.source === "ISN Follow-up" && <Badge className="bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300">Follow-up</Badge>}
                    </div>
                  </div>
                  <AttributionBadge />
                </div>

                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                  <Row label="Recipient" value={selectedShopper?.name || result.email} />
                  <Row label="Campaign" value={result.campaign_name || allCampaigns.find((c) => c.id === campaignId)?.name} />
                  <Row label="Shop" value={result.shop_name || shops.find((s) => s.id === shopId)?.shop_name} />
                  <Row label="Tracking" value="Enabled" ok />
                  <Row label="Email Open Tracking" value="Enabled" ok />
                  <Row label="Link Click Tracking" value="Enabled" ok />
                  <Row label="Response Tracking" value="Enabled" ok />
                </dl>

                {emailNotConfigured && (
                  <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                    SendGrid is not configured (EMAIL_PROVIDER=mock) — Send Email will simulate delivery only.
                    Set EMAIL_PROVIDER=sendgrid and SENDGRID_API_KEY to send real email.
                  </p>
                )}

                <div className="mt-4 flex flex-wrap gap-2">
                  {alreadySent ? (
                    <>
                      <span className="rounded-lg bg-slate-100 px-3 py-2 text-xs font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                        This invitation has already been sent.
                      </span>
                      <button className="btn-secondary" onClick={doFollowUp} disabled={busy === "followup"}>
                        {busy === "followup" ? <Spinner /> : null} Send Follow-Up
                      </button>
                    </>
                  ) : (
                    <button className="btn-primary" onClick={() => setShowSendConfirm(true)} disabled={!canSend || !!busy}>
                      {busy === "send" ? (
                        <><Spinner /> Sending through SendGrid…</>
                      ) : (
                        <><IconSend width={15} height={15} /> SEND EMAIL</>
                      )}
                    </button>
                  )}
                  {!showTestBox ? (
                    <button className="btn-secondary" onClick={() => setShowTestBox(true)}>
                      Send Test
                    </button>
                  ) : (
                    <div className="flex items-center gap-1.5">
                      <input
                        className="input h-9 w-52"
                        placeholder="your-test@email.com"
                        value={testEmail}
                        onChange={(e) => setTestEmail(e.target.value)}
                      />
                      <button className="btn-secondary h-9" onClick={doSendTest} disabled={busy === "test" || !testEmail.trim()}>
                        {busy === "test" ? <Spinner /> : "Send"}
                      </button>
                    </div>
                  )}
                </div>

                <div className="mt-4 rounded-lg border border-dashed border-slate-200 p-3 dark:border-slate-700">
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                    Demo simulation — writes real events to the database, clearly tagged SIMULATED
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <SimBtn label="Simulate Email Open" action="open" busy={busy} onClick={simulate} icon={<IconMail width={15} height={15} />} />
                    <SimBtn label="Simulate Click" action="click" busy={busy} onClick={simulate} icon={<IconCursor width={15} height={15} />} />
                    <SimBtn label="Simulate Accept" action="accept" busy={busy} onClick={simulate} icon={<IconTarget width={15} height={15} />} />
                  </div>
                </div>

                <div className="mt-4 grid gap-2">
                  <UrlField label="Tracking URL (click → redirect)" value={result.urls?.tracking_url} />
                  <UrlField label="Email open pixel URL" value={result.urls?.pixel_url} />
                </div>
              </div>

              {/* Email preview */}
              <div className="card overflow-hidden">
                <div className="border-b border-slate-200 p-4 dark:border-slate-800">
                  <div className="text-xs text-slate-400">From: {fromDisplay}</div>
                  <div className="text-sm font-semibold text-slate-900 dark:text-white">{previewSubject}</div>
                  <div className="text-xs text-slate-400">To: {recipientEmail}</div>
                </div>
                <iframe title="Email preview" srcDoc={previewHtml} className="h-[420px] w-full border-0 bg-white" />
                <div className="border-t border-slate-200 p-2.5 text-center text-[11px] text-slate-400 dark:border-slate-800">
                  Preview uses a non-firing pixel — it will not record an email open. Test emails reuse this
                  invitation's real tracking link, so clicking VIEW ASSIGNMENT in a test send will register a real click.
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <RecentEmails campaignId={campaignId} />

      {showSendConfirm && result && (
        <ConfirmModal
          title="Send Invitation?"
          onCancel={() => setShowSendConfirm(false)}
          onConfirm={doSend}
          busy={busy === "send"}
        >
          <Row label="Recipient" value={selectedShopper?.name || result.email} />
          <Row label="Email" value={recipientEmail} />
          <Row label="Campaign" value={allCampaigns.find((c) => c.id === campaignId)?.name} />
          <Row label="Shop" value={shops.find((s) => s.id === shopId)?.shop_name} />
        </ConfirmModal>
      )}

      {showSaveTemplate && (
        <ConfirmModal
          title="Save as Template"
          onCancel={() => setShowSaveTemplate(false)}
          onConfirm={saveTemplate}
          busy={false}
          confirmLabel="Save Template"
        >
          <label className="label">Template name</label>
          <input
            className="input"
            autoFocus
            value={newTemplateName}
            onChange={(e) => setNewTemplateName(e.target.value)}
            placeholder="e.g. Priority Retail Invitation"
          />
        </ConfirmModal>
      )}

      {bonusShop && (
        <BonusModal
          shop={bonusShop}
          campaignId={campaignId}
          onClose={() => setBonusShop(null)}
          onSaved={reloadShops}
        />
      )}
    </div>
  );
}

// Client-funded bonus money for a shop that isn't filled yet (see
// backend/app/models.py::ShopBonus). ShopperMatch never processes this
// payment — it just tracks the pledge and, once ISN marks the shop
// completed, emails a reminder to pay whichever shopper did it.
function BonusModal({
  shop,
  campaignId,
  onClose,
  onSaved,
}: {
  shop: any;
  campaignId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const existing = shop.bonus;
  const [amount, setAmount] = useState(existing ? String(existing.amount) : "");
  const [note, setNote] = useState(existing?.note || "");
  const [busy, setBusy] = useState(false);
  const awarded = !!existing?.completed_at;

  async function save() {
    const n = Number(amount);
    if (!n || n <= 0) {
      toast("Enter a bonus amount greater than 0", "error");
      return;
    }
    setBusy(true);
    try {
      await api.setShopBonus(campaignId, shop.id, Math.round(n), note.trim() || undefined);
      toast(`Bonus of ${fmtMoney(Math.round(n), shop.currency)} set for ${shop.shop_name}`, "success");
      onSaved();
      onClose();
    } catch (e: any) {
      toast(e?.message || "Failed to save bonus", "error");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api.removeShopBonus(campaignId, shop.id);
      toast(`Bonus removed for ${shop.shop_name}`, "success");
      onSaved();
      onClose();
    } catch (e: any) {
      toast(e?.message || "Failed to remove bonus", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full max-w-sm rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-900 dark:text-white">
            {existing ? "Edit Bonus" : "Add Bonus"} — {shop.shop_name}
          </h3>
          <button className="btn-ghost" onClick={onClose} aria-label="Close">
            <IconX />
          </button>
        </div>

        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          Extra incentive on top of standard compensation, funded and paid by you directly to the shopper —
          ShopperMatch does not process this payment. Whichever shopper completes this shop receives it, and
          you'll get an email reminder once ISN confirms the shop is done.
        </p>

        {awarded ? (
          <div className="mt-4 rounded-lg bg-teal-50 px-3 py-2 text-sm text-teal-700 dark:bg-teal-950/40 dark:text-teal-300">
            This bonus was already awarded to {existing.awarded_shopper_name || "a shopper"} and can no longer be
            edited.
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            <div>
              <label className="label">Bonus amount ({shop.currency})</label>
              <input
                className="input"
                type="number"
                min={1}
                autoFocus
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="e.g. 500"
              />
            </div>
            <div>
              <label className="label">Note (optional)</label>
              <input
                className="input"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. For a same-week visit"
              />
            </div>
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          {existing && !awarded && (
            <button className="btn-secondary mr-auto text-rose-600 dark:text-rose-400" onClick={remove} disabled={busy}>
              Remove
            </button>
          )}
          <button className="btn-secondary" onClick={onClose}>
            {awarded ? "Close" : "Cancel"}
          </button>
          {!awarded && (
            <button className="btn-primary" onClick={save} disabled={busy}>
              {busy ? <Spinner /> : null} Save Bonus
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function BulkResultPanel({
  result,
  sending,
  draftSubject,
  draftBodyDoc,
  recipientCount,
}: {
  result: { created: any[]; failed: any[] } | null;
  sending: boolean;
  draftSubject: string;
  draftBodyDoc: string;
  recipientCount: number;
}) {
  if (sending && !result) {
    return (
      <div className="card flex h-full min-h-[300px] flex-col items-center justify-center p-8 text-center">
        <Spinner className="h-6 w-6" />
        <div className="mt-4 text-sm font-semibold text-slate-700 dark:text-slate-200">Sending bulk batch(es)…</div>
      </div>
    );
  }
  if (!result) {
    return (
      <div className="card overflow-hidden">
        <div className="border-b border-slate-200 bg-amber-50 p-4 dark:border-slate-800 dark:bg-amber-950/30">
          <div className="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
            Draft preview — not sent yet
          </div>
          <div className="mt-0.5 text-xs text-amber-700/80 dark:text-amber-400/80">
            {recipientCount > 0
              ? `Same message goes to all ${recipientCount} selected shopper(s) — this shows it for the first one.`
              : "Select shoppers on the left to see who this goes to."}{" "}
            Keep editing above, then click <span className="font-semibold">Send Bulk Invitations</span> when ready.
          </div>
        </div>
        <div className="border-b border-slate-200 p-3 dark:border-slate-800">
          <div className="text-xs text-slate-400">Subject (rendered)</div>
          <div className="text-sm font-semibold text-slate-900 dark:text-white">{draftSubject}</div>
        </div>
        <iframe title="Draft email preview" srcDoc={draftBodyDoc} sandbox="" className="h-[420px] w-full border-0 bg-white" />
      </div>
    );
  }
  return (
    <div className="card p-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-2">
        <KpiCard label="Created & Queued" value={result.created.length} accent="emerald" />
        <KpiCard label="Failed" value={result.failed.length} accent="rose" />
      </div>
      <div className="mt-4 max-h-96 overflow-y-auto rounded-lg border border-slate-100 dark:border-slate-800">
        <table className="min-w-full text-sm">
          <thead className="border-b border-slate-100 dark:border-slate-800">
            <tr>
              <th className="th">Shopper</th>
              <th className="th">Reference</th>
              <th className="th">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
            {result.created.map((c: any) => (
              <tr key={c.invitation_id}>
                <td className="td">{c.shopper_name}</td>
                <td className="td font-mono text-xs text-slate-500">{c.reference}</td>
                <td className="td">
                  <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">Queued</Badge>
                </td>
              </tr>
            ))}
            {result.failed.map((f: any, i: number) => (
              <tr key={`f-${i}`}>
                <td className="td">{f.shopper_id}</td>
                <td className="td text-xs text-slate-500">—</td>
                <td className="td">
                  <Badge className="bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300">{f.error}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] text-slate-400">
        Queued invitations are delivered by the background outbox worker, respecting the daily send limit and
        batch delay shown on the Sequences tab.
      </p>
    </div>
  );
}

function Row({ label, value, ok }: { label: string; value: any; ok?: boolean }) {
  return (
    <>
      <dt className="text-slate-400">{label}</dt>
      <dd className={classNames("font-medium", ok ? "text-emerald-600 dark:text-emerald-400" : "text-slate-800 dark:text-slate-100")}>
        {ok ? "✓ " : ""}
        {value ?? "—"}
      </dd>
    </>
  );
}

function SimBtn({
  label,
  action,
  busy,
  onClick,
  icon,
}: {
  label: string;
  action: string;
  busy: string | null;
  onClick: (action: string, label: string) => void;
  icon: ReactNode;
}) {
  return (
    <button
      className="btn bg-slate-800 text-white hover:bg-slate-900 dark:bg-slate-700 dark:hover:bg-slate-600"
      disabled={!!busy}
      onClick={() => onClick(action, label)}
    >
      {busy === action ? <Spinner className="text-white" /> : icon}
      {label}
    </button>
  );
}

function UrlField({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="flex items-center gap-2">
      <div className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-800/40">
        <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
        <div className="truncate font-mono text-xs text-slate-600 dark:text-slate-300">{value}</div>
      </div>
      <CopyButton value={value} label="" />
    </div>
  );
}

function ConfirmModal({
  title,
  children,
  onCancel,
  onConfirm,
  busy,
  confirmLabel = "Send Email",
}: {
  title: string;
  children: ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
  busy: boolean;
  confirmLabel?: string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} />
      <div className="relative w-full max-w-sm rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-900 dark:text-white">{title}</h3>
          <button className="btn-ghost" onClick={onCancel} aria-label="Close">
            <IconX />
          </button>
        </div>
        <dl className="mt-4 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1.5 text-sm">{children}</dl>
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn-primary" onClick={onConfirm} disabled={busy}>
            {busy ? <Spinner /> : null} {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function RecentEmails({ campaignId }: { campaignId: string }) {
  const { data, loading, reload } = useApi(() => api.invitations({ campaign_id: campaignId || undefined, limit: 15 }), [campaignId]);

  useEffect(() => {
    const id = window.setInterval(reload, 6000);
    return () => window.clearInterval(id);
  }, [reload]);

  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="card">
      <div className="flex items-center justify-between border-b border-slate-100 p-4 dark:border-slate-800">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Recent Emails</h2>
        <span className="text-[11px] text-slate-400">Live: refreshes every 6s · click a row for the full timeline</span>
      </div>
      {loading && !data ? (
        <Loading label="Loading recent emails…" />
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead className="border-b border-slate-100 dark:border-slate-800">
              <tr>
                <th className="th">Shopper</th>
                <th className="th">Campaign</th>
                <th className="th hidden md:table-cell">Subject</th>
                <th className="th hidden lg:table-cell">Sent At</th>
                <th className="th text-center">Opened</th>
                <th className="th text-center">Clicked</th>
                <th className="th text-center">Visited</th>
                <th className="th hidden lg:table-cell">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
              {(data?.items || []).map((r: any) => (
                <tr
                  key={r.id}
                  className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40"
                  onClick={() => setSelected(r.id)}
                >
                  <td className="td font-medium text-slate-800 dark:text-slate-100">
                    {r.shopper_name}
                    <div className="text-[11px] font-normal text-slate-400">{r.reference}</div>
                  </td>
                  <td className="td">{r.campaign_name}</td>
                  <td className="td hidden max-w-[220px] truncate text-slate-500 md:table-cell">{r.subject}</td>
                  <td className="td hidden text-slate-500 lg:table-cell">{r.sent_at ? fmtDateTime(r.sent_at) : "—"}</td>
                  <td className="td text-center">{r.opened_at ? "✓" : "—"}</td>
                  <td className="td text-center">{r.clicked_at ? "✓" : "—"}</td>
                  <td className="td text-center">{r.visited_at ? "✓" : "—"}</td>
                  <td className="td hidden lg:table-cell">
                    <span className="badge bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300">
                      ISN Email
                    </span>
                  </td>
                </tr>
              ))}
              {(!data || data.items.length === 0) && (
                <tr>
                  <td colSpan={8} className="td py-10 text-center text-slate-400">
                    No emails yet — generate and send an invitation above.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {selected && <InvitationDrawer invitationId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

export function BulkSendStatusCard() {
  const { data, loading } = useApi(() => api.clientEmailStatus());
  if (loading && !data) return null;
  return (
    <div className="card p-5">
      <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Bulk-send limits</h2>
      <p className="mt-1 text-xs text-slate-400">
        Every send in a sequence flows through the same background outbox — these limits apply across all of your
        active sequences combined, not per sequence.
      </p>
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KpiCard label="Batch Size" value={data?.bulk_email_batch_size ?? "—"} accent="brand" />
        <KpiCard label="Daily Limit" value={data?.bulk_email_daily_limit ?? "—"} accent="indigo" />
        <KpiCard label="Batch Delay" value={data ? `${data.bulk_email_batch_delay_seconds}s` : "—"} accent="violet" />
        <KpiCard label="Sent (24h)" value={data ? `${data.sent_last_24h} / ${data.bulk_email_daily_limit}` : "—"} accent="emerald" />
      </div>
    </div>
  );
}
