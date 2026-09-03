// Thin typed fetch client. Requests default to same-origin relative URLs —
// works identically in dev (via Vite proxy) and when FastAPI serves the
// built SPA itself. Set VITE_API_BASE_URL (build-time env var) when the
// frontend is deployed separately from the backend (e.g. frontend on
// Vercel, backend on Railway/Render) so requests reach the right origin.
const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

function apiUrl(path: string): string {
  return path.startsWith("/") ? API_BASE + path : path;
}

const TOKEN_KEY = "sm_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  data: any;
  constructor(status: number, message: string, data?: any) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

type Options = { method?: string; body?: any; headers?: Record<string, string> };

async function request<T = any>(path: string, options: Options = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(apiUrl(path), {
    method: options.method || "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    if (res.status === 401) clearToken();
    const detail =
      (data && (data.detail || data.message)) || res.statusText || "Request failed";
    throw new ApiError(res.status, typeof detail === "string" ? detail : "Request failed", data);
  }
  return data as T;
}

// Binary export downloads (PDF/CSV/XLSX) — same bearer auth as `request`,
// but reads a blob instead of JSON and triggers a browser save.
export async function downloadFile(path: string, filename: string): Promise<void> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(apiUrl(path), { headers });
  if (!res.ok) {
    if (res.status === 401) clearToken();
    let detail = res.statusText || "Export failed";
    try {
      const data = await res.json();
      detail = data?.detail || data?.message || detail;
    } catch {
      /* body wasn't JSON — keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Generic multipart file upload — auth header only, no Content-Type (the
// browser sets the multipart boundary itself). Shared by anything that
// posts a File/FormData rather than JSON (voice audio, social post
// document/photo attachments).
async function uploadRequest(path: string, form: FormData): Promise<any> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(apiUrl(path), { method: "POST", headers, body: form });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    if (res.status === 401) clearToken();
    const detail = (data && (data.detail || data.message)) || res.statusText || "Request failed";
    throw new ApiError(res.status, typeof detail === "string" ? detail : "Request failed", data);
  }
  return data;
}

// Voice Assistant: text -> spoken audio (mp3 blob), for local <audio> playback.
async function voiceSpeakRequest(text: string): Promise<Blob> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(apiUrl("/api/voice/speak"), { method: "POST", headers, body: JSON.stringify({ text }) });
  if (!res.ok) {
    if (res.status === 401) clearToken();
    throw new ApiError(res.status, "Speech synthesis failed");
  }
  return res.blob();
}

function qs(params: Record<string, any> = {}): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== ""
  );
  if (!entries.length) return "";
  return "?" + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
}

export const api = {
  // Auth
  login: (email: string, password: string) =>
    request("/api/auth/login", { method: "POST", body: { email, password } }),
  me: () => request("/api/auth/me"),
  register: (body: { company_name: string; contact_name: string; email: string; password: string }) =>
    request("/api/auth/register", { method: "POST", body }),
  forgotPassword: (email: string) =>
    request("/api/auth/forgot-password", { method: "POST", body: { email } }),
  resetPassword: (token: string, newPassword: string) =>
    request("/api/auth/reset-password", { method: "POST", body: { token, new_password: newPassword } }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request("/api/auth/change-password", {
      method: "POST",
      body: { current_password: currentPassword, new_password: newPassword },
    }),

  // Dashboard & analytics
  dashboard: () => request("/api/dashboard/metrics"),
  trackingSummary: () => request("/api/tracking/summary"),
  trackingEvents: (params?: Record<string, any>) =>
    request("/api/tracking/events" + qs(params)),

  // Campaigns / shops / shoppers
  campaigns: (params?: Record<string, any>) => request("/api/campaigns" + qs(params)),
  campaign: (id: string) => request(`/api/campaigns/${id}`),
  campaignShops: (id: string) => request(`/api/campaigns/${id}/shops`),
  campaignMap: (id: string) => request(`/api/campaigns/${id}/map`),
  exportAdminCampaignReport: (campaignId: string, format: "csv" | "xlsx" | "pdf", campaignName: string) =>
    downloadFile(
      `/api/reports/campaigns/${campaignId}/export${qs({ format })}`,
      `${campaignName.replace(/\s+/g, "_")}_admin_report.${format}`
    ),
  campaignShoppers: (id: string) => request(`/api/campaigns/${id}/shoppers`),
  campaignOutreach: (id: string) => request(`/api/campaigns/${id}/outreach`),
  campaignTracking: (id: string) => request(`/api/campaigns/${id}/tracking`),
  campaignInsights: (id: string) => request(`/api/campaigns/${id}/insights`),
  campaignDistribution: (id: string) => request(`/api/campaigns/${id}/distribution`),
  generateDistributionImage: (id: string, message: string) =>
    request(`/api/campaigns/${id}/distribution/generate-image`, { method: "POST", body: { message } }),
  postCampaignDistribution: (
    id: string,
    message: string,
    imageUrl?: string | null,
    platforms?: string[],
    regions?: string[]
  ) =>
    request(`/api/campaigns/${id}/distribution/post`, {
      method: "POST",
      body: { message, image_url: imageUrl ?? null, platforms, regions },
    }),
  clientSocialAccounts: () => request("/api/client/social-accounts"),
  connectSocialAccount: (platform: string, accountName?: string) =>
    request("/api/client/social-accounts/connect", { method: "POST", body: { platform, account_name: accountName } }),
  disconnectSocialAccount: (platform: string) =>
    request(`/api/client/social-accounts/${platform}`, { method: "DELETE" }),
  // Social Media Automation
  facebookStatus: () => request("/api/social/facebook/status"),
  facebookConnect: () => request("/api/social/facebook/connect"),
  facebookPendingPages: (pendingId: string) => request(`/api/social/facebook/pending/${pendingId}`),
  facebookSelectPage: (pendingId: string, pageId: string) =>
    request("/api/social/facebook/select-page", { method: "POST", body: { pending_id: pendingId, page_id: pageId } }),
  socialPosts: (params?: Record<string, any>) => request("/api/social/posts" + qs(params)),
  socialPost: (id: string) => request(`/api/social/posts/${id}`),
  createSocialPost: (body: Record<string, any>) => request("/api/social/posts", { method: "POST", body }),
  updateSocialPost: (id: string, body: Record<string, any>) =>
    request(`/api/social/posts/${id}`, { method: "PATCH", body }),
  deleteSocialPost: (id: string) => request(`/api/social/posts/${id}`, { method: "DELETE" }),
  duplicateSocialPost: (id: string) => request(`/api/social/posts/${id}/duplicate`, { method: "POST" }),
  scheduleSocialPost: (id: string, scheduledAt: string, timezone: string) =>
    request(`/api/social/posts/${id}/schedule`, { method: "POST", body: { scheduled_at: scheduledAt, timezone } }),
  publishSocialPostNow: (id: string) => request(`/api/social/posts/${id}/publish`, { method: "POST" }),
  cancelSocialPost: (id: string) => request(`/api/social/posts/${id}/cancel`, { method: "POST" }),
  markSocialPostPosted: (id: string) => request(`/api/social/posts/${id}/mark-posted`, { method: "POST" }),
  generateSocialPostText: (id: string, body: Record<string, any>) =>
    request(`/api/social/posts/${id}/generate`, { method: "POST", body }),
  generateSocialPostImage: (id: string) => request(`/api/social/posts/${id}/generate-image`, { method: "POST" }),
  analyzeSocialPostDocument: (id: string, file: File) => {
    const form = new FormData();
    form.append("document", file);
    return uploadRequest(`/api/social/posts/${id}/analyze-document`, form);
  },
  generateSocialPostImageFromPhoto: (id: string, file: File) => {
    const form = new FormData();
    form.append("photo", file);
    return uploadRequest(`/api/social/posts/${id}/generate-image-from-photo`, form);
  },

  setShopBonus: (campaignId: string, shopId: string, amount: number, note?: string) =>
    request(`/api/campaigns/${campaignId}/shops/${shopId}/bonus`, {
      method: "POST",
      body: { amount, note: note || null },
    }),
  removeShopBonus: (campaignId: string, shopId: string) =>
    request(`/api/campaigns/${campaignId}/shops/${shopId}/bonus`, { method: "DELETE" }),
  completeShop: (shopId: string) => request(`/api/shops/${shopId}/complete`, { method: "POST" }),
  aiShopRecommendations: (campaignId: string, shopId: string, params?: Record<string, any>) =>
    request(`/api/campaigns/${campaignId}/shops/${shopId}/recommendations` + qs(params)),
  approveAiRecommendations: (campaignId: string, shopId: string, shopperIds: string[]) =>
    request(`/api/campaigns/${campaignId}/shops/${shopId}/recommendations/approve`, {
      method: "POST",
      body: { shopper_ids: shopperIds },
    }),
  shops: (campaignId?: string) => request("/api/shops" + qs({ campaign_id: campaignId })),
  shop: (id: string) => request(`/api/shops/${id}`),
  setShopOverSelection: (id: string, allow: boolean) =>
    request(`/api/shops/${id}/over-selection`, { method: "PATCH", body: { allow } }),
  shopRecommendations: (id: string, limit = 10) =>
    request(`/api/shops/${id}/recommendations` + qs({ limit })),
  shoppers: (q?: string, availability?: string) =>
    request("/api/shoppers" + qs({ q, availability })),
  shopper: (id: string) => request(`/api/shoppers/${id}`),
  shopperCampaignHistory: (id: string) => request(`/api/shoppers/${id}/campaign-history`),

  // Notifications
  notifications: (limit = 50) => request("/api/notifications" + qs({ limit })),
  recommendations: (shopId?: string, limit = 10) =>
    request("/api/recommendations" + qs({ shop_id: shopId, limit })),

  // Invitations
  invitations: (params?: Record<string, any>) => request("/api/invitations" + qs(params)),
  invitation: (id: string) => request(`/api/invitations/${id}`),
  createInvitation: (body: any) => request("/api/invitations", { method: "POST", body }),
  createBulkInvitations: (body: any) => request("/api/invitations/bulk", { method: "POST", body }),
  previewEmail: (id: string, preview = true) =>
    request(`/api/invitations/${id}/email` + qs({ preview })),
  simulate: (id: string, action: string) =>
    request(`/api/invitations/${id}/simulate`, { method: "POST", body: { action } }),
  sendInvitation: (id: string, customSubject?: string, customHtml?: string) =>
    request(`/api/invitations/${id}/send`, {
      method: "POST",
      body: customSubject && customHtml ? { custom_subject: customSubject, custom_html: customHtml } : {},
    }),
  sendTestInvitation: (id: string, testEmail: string) =>
    request(`/api/invitations/${id}/send-test`, { method: "POST", body: { test_email: testEmail } }),
  followUpInvitation: (id: string) => request(`/api/invitations/${id}/follow-up`, { method: "POST" }),

  // Email templates
  emailTemplates: () => request("/api/email-templates"),
  createEmailTemplate: (body: { name: string; subject: string; html_body: string; active?: boolean }) =>
    request("/api/email-templates", { method: "POST", body }),
  updateEmailTemplate: (id: string, body: Record<string, any>) =>
    request(`/api/email-templates/${id}`, { method: "PUT", body }),
  deleteEmailTemplate: (id: string) => request(`/api/email-templates/${id}`, { method: "DELETE" }),
  duplicateEmailTemplate: (id: string) => request(`/api/email-templates/${id}/duplicate`, { method: "POST" }),

  // Public (shopper landing)
  sampleInvitation: () => request("/api/public/sample-invitation"),
  publicInvitation: (token: string) => request(`/api/public/invitations/${token}`),
  respond: (token: string, response: "accepted" | "declined", note?: string) =>
    request(`/api/invitations/${token}/respond`, {
      method: "POST",
      body: { response, note },
    }),

  // Admin User Management
  adminClientUsers: () => request("/api/admin/users/clients"),
  adminShopperUsers: () => request("/api/admin/users/shoppers"),
  exportAdminClientUsers: (format: "csv" | "xlsx" | "pdf") =>
    downloadFile(`/api/admin/users/clients/export${qs({ format })}`, `client_users.${format}`),
  exportAdminShopperUsers: (format: "csv" | "xlsx" | "pdf") =>
    downloadFile(`/api/admin/users/shoppers/export${qs({ format })}`, `shopper_users.${format}`),
  exportAdminAllUsers: (format: "csv" | "xlsx" | "pdf") =>
    downloadFile(`/api/admin/users/export-all${qs({ format })}`, `all_users.${format}`),
  adminCreateClient: (body: { company_name: string; contact_name: string; email: string; password: string }) =>
    request("/api/admin/users/clients", { method: "POST", body }),
  adminClientActivitySummary: () => request("/api/admin/users/clients/activity-summary"),
  adminClientActivityDetail: (clientId: string) => request(`/api/admin/users/clients/${clientId}/activity`),
  exportAdminClientActivity: (format: "csv" | "xlsx" | "pdf") =>
    downloadFile(`/api/admin/users/clients/activity-summary/export${qs({ format })}`, `client_activity.${format}`),

  // Admin extras
  auditLogs: () => request("/api/audit-logs"),
  insights: () => request("/api/insights"),
  settingsInfo: () => request("/api/settings"),
  health: () => request("/api/health"),

  // Integrations
  integrations: () => request("/api/integrations"),
  integration: (provider: string) => request(`/api/integrations/${provider}`),
  updateIntegrationConfig: (provider: string, body: { configuration?: Record<string, any>; secrets?: Record<string, any>; enabled?: boolean }) =>
    request(`/api/integrations/${provider}/config`, { method: "PUT", body }),
  testIntegration: (provider: string) => request(`/api/integrations/${provider}/test`, { method: "POST" }),
  sendTestEmail: (testEmail: string) =>
    request("/api/integrations/email/test-send", { method: "POST", body: { test_email: testEmail } }),
  startSassieSync: () => request("/api/integrations/sassie/sync", { method: "POST" }),
  syncLogs: () => request("/api/integrations/sync-logs"),

  // AI intelligence layer
  aiParseRequirements: (text: string, campaignId?: string) =>
    request("/api/ai/parse-requirements", { method: "POST", body: { text, campaign_id: campaignId } }),
  aiAcceptanceProbability: (shopperId: string, shopId?: string) =>
    request("/api/ai/acceptance-probability" + qs({ shopper_id: shopperId, shop_id: shopId })),
  aiCampaignHealth: (campaignId: string) => request(`/api/ai/campaigns/${campaignId}/health`),
  aiCampaignPerformance: (campaignId: string) => request(`/api/ai/campaigns/${campaignId}/performance`),
  aiOptimizeAssignments: (campaignId: string, radiusKm?: number) =>
    request(`/api/ai/campaigns/${campaignId}/optimize-assignments` + qs({ radius_km: radiusKm }), { method: "POST" }),
  aiAnomalies: () => request("/api/ai/anomalies"),
  aiDataQuality: () => request("/api/ai/data-quality"),
  aiFeedbackAnalysis: (campaignId: string) => request(`/api/ai/campaigns/${campaignId}/feedback-analysis`),
  aiAsk: (question: string) => request("/api/ai/ask", { method: "POST", body: { question } }),
  aiNextBestActions: () => request("/api/ai/next-best-actions"),
  aiPersonalizeEmail: (campaignId: string, shopId: string, shopperId: string) =>
    request("/api/ai/personalize-email", {
      method: "POST",
      body: { campaign_id: campaignId, shop_id: shopId, shopper_id: shopperId },
    }),
  aiOutreachPriority: (campaignId: string, shopId: string, limit = 10) =>
    request(`/api/ai/campaigns/${campaignId}/shops/${shopId}/outreach-priority` + qs({ limit })),
  aiActionCenter: () => request("/api/ai/action-center"),

  // Email Automation
  automations: (campaignId?: string) => request("/api/automations" + qs({ campaign_id: campaignId })),
  automation: (id: string) => request(`/api/automations/${id}`),
  createAutomation: (body: {
    campaign_id: string;
    // Omit/null for a campaign-wide automation (spans every shop in the
    // campaign) — each shopper's own shop is then supplied separately via
    // addAutomationShoppers's shopIds.
    shop_id?: string | null;
    name: string;
    // Ordered — index 0 is step 1. Longer than 3 gives each extra step
    // (most commonly each batch-emailing wave) its own template.
    step_template_ids?: (string | null)[];
    wait_days?: number;
    scheduled_start_at?: string | null;
    batch_size?: number | null;
    total_iterations?: number;
    voice_call_enabled?: boolean;
    voice_call_delay_days?: number;
    voice_call_retry_gap_days?: number;
    voice_call_max_attempts?: number;
  }) => request("/api/automations", { method: "POST", body }),
  automationVoiceCalls: (automationId: string) => request(`/api/voice-calls/automations/${automationId}`),
  addAutomationShoppers: (id: string, shopperIds: string[], shopIds?: string[]) =>
    request(`/api/automations/${id}/shoppers`, {
      method: "POST",
      body: { shopper_ids: shopperIds, ...(shopIds ? { shop_ids: shopIds } : {}) },
    }),
  removeAutomationShopper: (id: string, shopperId: string) =>
    request(`/api/automations/${id}/shoppers/${shopperId}`, { method: "DELETE" }),
  automationPreview: (id: string, shopperId: string, step: number) =>
    request(`/api/automations/${id}/preview` + qs({ shopper_id: shopperId, step })),
  startAutomation: (id: string) => request(`/api/automations/${id}/start`, { method: "POST" }),
  pauseAutomation: (id: string) => request(`/api/automations/${id}/pause`, { method: "POST" }),
  resumeAutomation: (id: string) => request(`/api/automations/${id}/resume`, { method: "POST" }),
  stopAutomation: (id: string) => request(`/api/automations/${id}/stop`, { method: "POST" }),
  bulkStartAutomations: (campaignIds: string[], shoppersPerShop: number, startImmediately: boolean) =>
    request("/api/automations/bulk-start", {
      method: "POST",
      body: { campaign_ids: campaignIds, shoppers_per_shop: shoppersPerShop, start_immediately: startImmediately },
    }),

  // Bulk campaign status change
  bulkCampaignStatus: (campaignIds: string[], status: "active" | "upcoming" | "completed" | "cancelled") =>
    request("/api/campaigns/bulk/status", { method: "POST", body: { campaign_ids: campaignIds, status } }),

  // AI template generation
  aiGenerateTemplate: (goal: string, tone: string) =>
    request("/api/ai/generate-template", { method: "POST", body: { goal, tone } }),

  // Client Portal — every call is scoped server-side to the logged-in
  // client's own client_id (deps.py::require_client); nothing here accepts
  // a client_id parameter from the frontend.
  clientProfile: () => request("/api/client/profile"),
  clientDeactivateAccount: (password: string) =>
    request("/api/client/account/deactivate", { method: "POST", body: { password } }),
  clientDeleteAccount: (password: string) =>
    request("/api/client/account/delete", { method: "POST", body: { password } }),
  clientDashboard: () => request("/api/client/dashboard"),
  clientCampaigns: (status?: string) => request("/api/client/campaigns" + qs({ status })),
  clientCampaign: (id: string) => request(`/api/client/campaigns/${id}`),
  clientCampaignShops: (id: string) => request(`/api/client/campaigns/${id}/shops`),
  clientInsights: (campaignId?: string) => request("/api/client/insights" + qs({ campaign_id: campaignId })),
  clientReports: (campaignId?: string) => request("/api/client/reports" + qs({ campaign_id: campaignId })),
  exportClientCampaignReport: (campaignId: string, format: "csv" | "xlsx" | "pdf", campaignName: string) =>
    downloadFile(
      `/api/client/reports/campaigns/${campaignId}/export${qs({ format })}`,
      `${campaignName.replace(/\s+/g, "_")}_report.${format}`
    ),
  clientEmailStatus: () => request("/api/client/email-status"),
  clientTracking: () => request("/api/client/tracking"),
  clientTrackingCampaign: (campaignId: string) => request(`/api/client/tracking/campaign/${campaignId}`),

  // ---- Voice Assistant ----
  voiceStatus: () => request("/api/voice/status"),
  voiceCommand: (opts: {
    audioBlob?: Blob;
    transcript?: string;
    context: Record<string, any>;
    history?: { role: "user" | "assistant"; content: string }[];
  }) => {
    const form = new FormData();
    if (opts.audioBlob) form.append("audio", opts.audioBlob, "clip.webm");
    if (opts.transcript) form.append("transcript", opts.transcript);
    form.append("context", JSON.stringify(opts.context));
    if (opts.history) form.append("history", JSON.stringify(opts.history));
    return uploadRequest("/api/voice/command", form);
  },
  voiceSpeak: (text: string) => voiceSpeakRequest(text),
};
