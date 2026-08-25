import { useEffect, useState } from "react";
import { Badge, EmptyState, Loading, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

const VARIABLES = [
  "shopper_name", "campaign_name", "client_name", "shop_name",
  "location", "compensation", "deadline", "assignment_link", "invitation_id",
];

const BLANK = { name: "", subject: "", html_body: "<p>Hi {{shopper_name}},</p>\n<p></p>\n<p>Thank you,<br/>ShopperMatch.AI Team</p>", active: true };

export function EmailTemplatesPanel({ compact }: { compact?: boolean }) {
  const templates = useApi(() => api.emailTemplates());
  const toast = useToast();
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState<any>(BLANK);
  const [saving, setSaving] = useState(false);
  const [showAiGenerate, setShowAiGenerate] = useState(false);

  useEffect(() => {
    if (editing) setForm({ name: editing.name, subject: editing.subject, html_body: editing.html_body, active: editing.active });
    else setForm(BLANK);
  }, [editing]);

  const items = templates.data?.items || [];

  async function save() {
    if (!form.name.trim() || !form.subject.trim() || !form.html_body.trim()) {
      toast("Name, subject and body are required.", "error");
      return;
    }
    setSaving(true);
    try {
      if (editing?.id) {
        await api.updateEmailTemplate(editing.id, form);
        toast(`Template "${form.name}" updated.`, "success");
      } else {
        await api.createEmailTemplate(form);
        toast(`Template "${form.name}" created.`, "success");
      }
      setEditing(null);
      templates.reload();
    } catch (e: any) {
      toast(e?.message || "Failed to save template", "error");
    } finally {
      setSaving(false);
    }
  }

  async function duplicate(id: string) {
    try {
      await api.duplicateEmailTemplate(id);
      templates.reload();
    } catch (e: any) {
      toast(e?.message || "Failed to duplicate template", "error");
    }
  }

  async function remove(id: string, name: string) {
    if (!confirm(`Delete template "${name}"? This cannot be undone.`)) return;
    try {
      await api.deleteEmailTemplate(id);
      toast(`Template "${name}" deleted.`, "success");
      templates.reload();
    } catch (e: any) {
      toast(e?.message || "Failed to delete template", "error");
    }
  }

  if (templates.loading && !templates.data) return <Loading label="Loading email templates…" />;
  if (templates.error) return <ErrorBox message={templates.error} onRetry={templates.reload} />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {!compact ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Used by Outreach and Outreach Sequences. The three defaults (Initial Invitation, Reminder, Final Reminder)
            power automation sequences unless you pick your own.
          </p>
        ) : (
          <span />
        )}
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={() => setShowAiGenerate(true)}>
            ✨ Generate with AI
          </button>
          <button className="btn-primary" onClick={() => setEditing({})}>
            + New Template
          </button>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="card">
          <EmptyState title="No templates yet" hint="Create your first reusable email template." />
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {items.map((t: any) => (
            <div key={t.id} className="card flex flex-col p-5">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-semibold text-slate-900 dark:text-white">{t.name}</div>
                  <div className="truncate text-xs text-slate-400">{t.subject}</div>
                </div>
                <Badge className={t.active ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300" : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"}>
                  {t.active ? "Active" : "Inactive"}
                </Badge>
              </div>
              <div
                className="mt-3 flex-1 overflow-hidden rounded-lg border border-slate-100 bg-slate-50 p-2 text-[11px] leading-snug text-slate-500 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-400"
                style={{ maxHeight: 90 }}
                dangerouslySetInnerHTML={{ __html: t.html_body }}
              />
              <div className="mt-3 text-[11px] text-slate-400">Updated {fmtDateTime(t.updated_at)}</div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button className="btn-secondary h-8 px-2.5 text-xs" onClick={() => setEditing(t)}>
                  Edit
                </button>
                <button
                  className="btn-secondary h-8 px-2.5 text-xs"
                  onClick={async () => {
                    await api.updateEmailTemplate(t.id, { active: !t.active });
                    templates.reload();
                  }}
                >
                  {t.active ? "Deactivate" : "Activate"}
                </button>
                <button className="btn-secondary h-8 px-2.5 text-xs" onClick={() => duplicate(t.id)}>
                  Duplicate
                </button>
                <button className="btn-secondary h-8 px-2.5 text-xs text-rose-600" onClick={() => remove(t.id, t.name)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {editing !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={() => setEditing(null)} />
          <div className="relative w-full max-w-2xl rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
            <h3 className="text-base font-bold text-slate-900 dark:text-white">
              {editing?.id ? "Edit Template" : "New Template"}
            </h3>
            <div className="mt-4 space-y-3">
              <div>
                <label className="label">Name</label>
                <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div>
                <label className="label">Subject</label>
                <input className="input" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
              </div>
              <div>
                <label className="label">Body (HTML)</label>
                <textarea
                  className="input h-48 resize-y font-mono text-xs leading-relaxed"
                  value={form.html_body}
                  onChange={(e) => setForm({ ...form, html_body: e.target.value })}
                />
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {VARIABLES.map((v) => (
                    <button
                      key={v}
                      type="button"
                      className="rounded-md bg-slate-100 px-2 py-1 text-[11px] font-mono text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300"
                      onClick={() => setForm({ ...form, html_body: form.html_body + `{{${v}}}` })}
                    >
                      {`{{${v}}}`}
                    </button>
                  ))}
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
                <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
                Active
              </label>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button className="btn-secondary" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button className="btn-primary" onClick={save} disabled={saving}>
                {saving ? <Spinner /> : null} Save Template
              </button>
            </div>
          </div>
        </div>
      )}

      {showAiGenerate && (
        <AiGenerateModal
          onClose={() => setShowAiGenerate(false)}
          onGenerated={(draft) => {
            setShowAiGenerate(false);
            setEditing({});
            setForm({ name: draft.name, subject: draft.subject, html_body: draft.html_body, active: true });
          }}
        />
      )}
    </div>
  );
}

function AiGenerateModal({
  onClose,
  onGenerated,
}: {
  onClose: () => void;
  onGenerated: (draft: { name: string; subject: string; html_body: string }) => void;
}) {
  const toast = useToast();
  const [goal, setGoal] = useState("");
  const [tone, setTone] = useState("professional");
  const [generating, setGenerating] = useState(false);

  async function generate() {
    if (!goal.trim()) {
      toast("Describe what this email should say first.", "error");
      return;
    }
    setGenerating(true);
    try {
      const draft = await api.aiGenerateTemplate(goal.trim(), tone);
      toast("Draft generated — review and edit before saving.", "success");
      onGenerated(draft);
    } catch (e: any) {
      toast(e?.message || "Failed to generate template", "error");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full max-w-md rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900">
        <h3 className="text-base font-bold text-slate-900 dark:text-white">✨ Generate with AI</h3>
        <p className="mt-1 text-xs text-slate-400">
          Describe what this email is for — the draft uses the same variables as every other template
          ({"{{shopper_name}}"}, {"{{shop_name}}"}, etc.) so it's ready to use immediately.
        </p>
        <div className="mt-4">
          <label className="label">What should this email say?</label>
          <textarea
            className="input h-24 resize-none text-sm"
            autoFocus
            placeholder="e.g. Invite shoppers to a weekend flash audit with a bonus incentive"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
        </div>
        <div className="mt-3">
          <label className="label">Tone</label>
          <select className="input" value={tone} onChange={(e) => setTone(e.target.value)}>
            <option value="professional">Professional</option>
            <option value="friendly">Friendly</option>
            <option value="urgent">Urgent</option>
          </select>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={generate} disabled={generating}>
            {generating ? <Spinner /> : null} Generate Draft
          </button>
        </div>
      </div>
    </div>
  );
}
