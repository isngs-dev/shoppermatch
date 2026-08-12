// Thin typed fetch client. All requests are same-origin relative URLs so this
// works identically in dev (via Vite proxy) and in production (FastAPI serves
// the built SPA). Auth uses a bearer token kept in localStorage.

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

  const res = await fetch(path, {
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

  // Dashboard & analytics
  dashboard: () => request("/api/dashboard/metrics"),
  trackingSummary: () => request("/api/tracking/summary"),
  trackingEvents: (params?: Record<string, any>) =>
    request("/api/tracking/events" + qs(params)),

  // Campaigns / shops / shoppers
  campaigns: (params?: Record<string, any>) => request("/api/campaigns" + qs(params)),
  campaign: (id: string) => request(`/api/campaigns/${id}`),
  campaignShops: (id: string) => request(`/api/campaigns/${id}/shops`),
  campaignShoppers: (id: string) => request(`/api/campaigns/${id}/shoppers`),
  campaignOutreach: (id: string) => request(`/api/campaigns/${id}/outreach`),
  campaignTracking: (id: string) => request(`/api/campaigns/${id}/tracking`),
  campaignInsights: (id: string) => request(`/api/campaigns/${id}/insights`),
  aiShopRecommendations: (campaignId: string, shopId: string, params?: Record<string, any>) =>
    request(`/api/campaigns/${campaignId}/shops/${shopId}/recommendations` + qs(params)),
  approveAiRecommendations: (campaignId: string, shopId: string, shopperIds: string[]) =>
    request(`/api/campaigns/${campaignId}/shops/${shopId}/recommendations/approve`, {
      method: "POST",
      body: { shopper_ids: shopperIds },
    }),
  shops: (campaignId?: string) => request("/api/shops" + qs({ campaign_id: campaignId })),
  shop: (id: string) => request(`/api/shops/${id}`),
  shopRecommendations: (id: string, limit = 10) =>
    request(`/api/shops/${id}/recommendations` + qs({ limit })),
  shoppers: (q?: string, availability?: string) =>
    request("/api/shoppers" + qs({ q, availability })),
  shopper: (id: string) => request(`/api/shoppers/${id}`),
  recommendations: (shopId?: string, limit = 10) =>
    request("/api/recommendations" + qs({ shop_id: shopId, limit })),

  // Invitations
  invitations: (params?: Record<string, any>) => request("/api/invitations" + qs(params)),
  invitation: (id: string) => request(`/api/invitations/${id}`),
  createInvitation: (body: any) => request("/api/invitations", { method: "POST", body }),
  previewEmail: (id: string, preview = true) =>
    request(`/api/invitations/${id}/email` + qs({ preview })),
  simulate: (id: string, action: string) =>
    request(`/api/invitations/${id}/simulate`, { method: "POST", body: { action } }),
  sendInvitation: (id: string) => request(`/api/invitations/${id}/send`, { method: "POST" }),
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

  // Public (shopper landing)
  sampleInvitation: () => request("/api/public/sample-invitation"),
  publicInvitation: (token: string) => request(`/api/public/invitations/${token}`),
  respond: (token: string, response: "accepted" | "declined", note?: string) =>
    request(`/api/invitations/${token}/respond`, {
      method: "POST",
      body: { response, note },
    }),

  // Admin extras
  auditLogs: () => request("/api/audit-logs"),
  insights: () => request("/api/insights"),
  integrations: () => request("/api/integrations"),
  settingsInfo: () => request("/api/settings"),
  health: () => request("/api/health"),
};
