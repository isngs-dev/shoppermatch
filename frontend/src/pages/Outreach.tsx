import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { AttributionBadge } from "../components/Attribution";
import { IconCursor, IconMail, IconSend, IconTarget, IconX } from "../components/Icons";
import { Badge, CopyButton, Loading, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
import { classNames, fmtDateTime, statusBadgeClass } from "../lib/format";
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

function builtinBody(intro: string) {
  return (
    `<p>Hi {{shopper_name}},</p>\n<p>${intro}</p>\n` +
    "<p>Campaign: {{campaign_name}}<br/>Shop: {{shop_name}}<br/>Location: {{location}}<br/>" +
    "Compensation: {{compensation}}<br/>Deadline: {{deadline}}</p>\n" +
    `<p>${ASSIGNMENT_BUTTON}</p>\n<p>Thank you,<br/>ISN Shopper Recruitment Team</p>`
  );
}

const BUILTIN_TEMPLATES: Record<string, { name: string; subject: string; body: string }> = {
  standard: {
    name: "Standard Invitation",
    subject: "Mystery Shopping Opportunity — {{shop_name}}",
    body: builtinBody("We have a new mystery shopping opportunity that may be a good match for you."),
  },
  urgent: {
    name: "Urgent Assignment",
    subject: "Urgent: Mystery Shopper Needed — {{shop_name}}",
    body: builtinBody("We urgently need a shopper for this assignment — spots are limited and closing soon."),
  },
  bonus: {
    name: "Bonus Opportunity",
    subject: "Bonus Opportunity — {{shop_name}}",
    body: builtinBody("This assignment comes with a bonus incentive on top of standard compensation."),
  },
  reminder: {
    name: "Reminder",
    subject: "Reminder — {{shop_name}}: your invitation is waiting",
    body: builtinBody("Just a reminder that this mystery shopping opportunity is still open for you."),
  },
  followup: {
    name: "Follow-Up",
    subject: "Following up — {{shop_name}}",
    body: builtinBody("Following up on our earlier invitation in case it got buried in your inbox."),
  },
  custom: {
    name: "Custom Email",
    subject: "",
    body: "<p>Hi {{shopper_name}},</p>\n<p></p>\n<p>Thank you,<br/>ISN Shopper Recruitment Team</p>",
  },
};

type FocusTarget = "subject" | "body";

export function Outreach() {
  const toast = useToast();
  const [searchParams] = useSearchParams();
  const preselectedCampaignId = searchParams.get("campaign") || "";

  const campaigns = useApi(() => api.campaigns());
  const shoppers = useApi(() => api.shoppers());
  const templatesApi = useApi(() => api.emailTemplates());
  const settingsApi = useApi(() => api.settingsInfo());

  const [campaignId, setCampaignId] = useState("");
  const [shopId, setShopId] = useState("");
  const [shopperId, setShopperId] = useState("");
  const [recipientEmail, setRecipientEmail] = useState("");
  const [shops, setShops] = useState<any[]>([]);
  const [templateKey, setTemplateKey] = useState("standard");
  const [subject, setSubject] = useState(BUILTIN_TEMPLATES.standard.subject);
  const [body, setBody] = useState(BUILTIN_TEMPLATES.standard.body);

  const [generating, setGenerating] = useState(false);
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

  const subjectRef = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const lastFocused = useRef<FocusTarget>("body");

  useEffect(() => {
    if (campaigns.data && !campaignId) {
      const preselected = preselectedCampaignId
        ? campaigns.data.items.find((c: any) => c.id === preselectedCampaignId)
        : null;
      setCampaignId(preselected?.id || campaigns.data.items[0]?.id || "");
    }
  }, [campaigns.data]);

  useEffect(() => {
    if (shoppers.data && !shopperId) {
      const sarah = shoppers.data.items.find((s: any) => s.name === "Sarah Johnson");
      setShopperId(sarah?.id || shoppers.data.items[0]?.id || "");
    }
  }, [shoppers.data]);

  useEffect(() => {
    if (!campaignId) return;
    api.shops(campaignId).then((r) => {
      setShops(r.items);
      setShopId(r.items[0]?.id || "");
    });
  }, [campaignId]);

  const selectedShopper = useMemo(
    () => shoppers.data?.items.find((s: any) => s.id === shopperId),
    [shoppers.data, shopperId]
  );
  useEffect(() => {
    setRecipientEmail(selectedShopper?.email || "");
  }, [selectedShopper?.email, shopperId]);

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
    const bt = BUILTIN_TEMPLATES[key];
    if (bt) {
      setSubject(bt.subject);
      setBody(bt.body);
    }
  }

  function insertAtCursor(text: string) {
    const target = lastFocused.current;
    if (target === "subject" && subjectRef.current) {
      const el = subjectRef.current;
      const start = el.selectionStart ?? subject.length;
      const end = el.selectionEnd ?? subject.length;
      const next = subject.slice(0, start) + text + subject.slice(end);
      setSubject(next);
      requestAnimationFrame(() => el.setSelectionRange(start + text.length, start + text.length));
    } else if (bodyRef.current) {
      const el = bodyRef.current;
      const start = el.selectionStart ?? body.length;
      const end = el.selectionEnd ?? body.length;
      const next = body.slice(0, start) + text + body.slice(end);
      setBody(next);
      requestAnimationFrame(() => el.setSelectionRange(start + text.length, start + text.length));
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
      const inv = await api.createInvitation({
        campaign_id: campaignId,
        shop_id: shopId,
        shopper_id: shopperId,
        recipient_email: recipientEmail.trim(),
        auto_send: false,
        custom_subject: subject,
        custom_html: body,
      });
      setResult(inv);
      toast(`Invitation ${inv.reference} generated. Preview it, then Send Email.`, "success");
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

  if (campaigns.loading || shoppers.loading) return <Loading label="Loading outreach…" />;

  const fromDisplay = settingsApi.data
    ? `${settingsApi.data.email_from}`
    : "ISN Shopper Recruitment";
  const emailNotConfigured = settingsApi.data?.email_provider === "mock";
  const alreadySent = !!result?.sent_at || queuedLocally;
  const canSend = !!result && !alreadySent && !!subject.trim() && !!body.trim() && !!recipientEmail.trim();
  const previewHtml = result?.email_preview?.html || "";
  const previewSubject = result?.email_preview?.subject || subject;

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-5">
        {/* Left: selectors + composer */}
        <div className="space-y-4 lg:col-span-2">
          <div className="card p-5">
            <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Outreach</h2>
            <div className="mt-4 space-y-4">
              <div>
                <label className="label">Campaign</label>
                <select className="input" value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
                  {campaigns.data.items.map((c: any) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Shop</label>
                <select className="input" value={shopId} onChange={(e) => setShopId(e.target.value)}>
                  {shops.map((s: any) => (
                    <option key={s.id} value={s.id}>
                      {s.shop_name} — {s.city}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Shopper</label>
                <select className="input" value={shopperId} onChange={(e) => setShopperId(e.target.value)}>
                  {shoppers.data.items.map((s: any) => (
                    <option key={s.id} value={s.id}>
                      {s.name} — {s.city} ({s.availability_status})
                    </option>
                  ))}
                </select>
              </div>
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
                  Defaults to {selectedShopper?.email || "the shopper's email"}; editable for this invitation only.
                </p>
              </div>
              <div>
                <label className="label">Template</label>
                <select className="input" value={templateKey} onChange={(e) => applyTemplate(e.target.value)}>
                  <optgroup label="Built-in">
                    {Object.entries(BUILTIN_TEMPLATES).map(([key, t]) => (
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

          {/* Composer */}
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
                  {recipientEmail || "—"}
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
              <label className="label">Body (HTML)</label>
              <textarea
                ref={bodyRef}
                className="input h-56 resize-y font-mono text-xs leading-relaxed"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                onFocus={() => (lastFocused.current = "body")}
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
            </div>

            <button className="btn-primary mt-4 w-full py-2.5" onClick={generate} disabled={generating}>
              {generating ? <Spinner /> : <><IconSend width={16} height={16} /> Generate Invitation</>}
            </button>
          </div>
        </div>

        {/* Right: preview + tracking + send */}
        <div className="lg:col-span-3">
          {!result ? (
            <div className="card flex h-full min-h-[300px] flex-col items-center justify-center p-8 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-50 text-brand-500 dark:bg-brand-950">
                <IconTarget />
              </div>
              <div className="mt-4 text-sm font-semibold text-slate-700 dark:text-slate-200">
                No invitation generated yet
              </div>
              <div className="mt-1 max-w-sm text-xs text-slate-400">
                Compose the email on the left, then click <span className="font-semibold">Generate Invitation</span> to
                create a unique tracking token and preview the rendered email.
              </div>
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
                  <Row label="Campaign" value={result.campaign_name || campaigns.data.items.find((c: any) => c.id === campaignId)?.name} />
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
                      {busy === "send" ? <Spinner /> : <IconSend width={15} height={15} />} SEND EMAIL
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
          <Row label="Campaign" value={campaigns.data.items.find((c: any) => c.id === campaignId)?.name} />
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

  return (
    <div className="card">
      <div className="flex items-center justify-between border-b border-slate-100 p-4 dark:border-slate-800">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Recent Emails</h2>
        <span className="text-[11px] text-slate-400">Live: refreshes every 6s</span>
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
                <th className="th text-center">Delivery</th>
                <th className="th text-center">Opened</th>
                <th className="th text-center">Clicked</th>
                <th className="th">Response</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">
              {(data?.items || []).map((r: any) => (
                <tr key={r.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                  <td className="td font-medium text-slate-800 dark:text-slate-100">
                    {r.shopper_name}
                    <div className="text-[11px] font-normal text-slate-400">{r.reference}</div>
                  </td>
                  <td className="td">{r.campaign_name}</td>
                  <td className="td hidden max-w-[220px] truncate text-slate-500 md:table-cell">{r.subject}</td>
                  <td className="td hidden text-slate-500 lg:table-cell">{r.sent_at ? fmtDateTime(r.sent_at) : "—"}</td>
                  <td className="td text-center">
                    {r.delivered_at ? "Delivered ✓" : r.sent_at ? "Sent ✓" : "—"}
                  </td>
                  <td className="td text-center">{r.opened_at ? "✓" : "—"}</td>
                  <td className="td text-center">{r.clicked_at ? "✓" : "—"}</td>
                  <td className="td">
                    <Badge className={statusBadgeClass(r.response || "pending")}>{r.response || "Pending"}</Badge>
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
    </div>
  );
}
