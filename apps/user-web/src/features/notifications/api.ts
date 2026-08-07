import { useAuthStore } from "@/stores/auth";
import { resolveApiBaseUrl } from "@/config/api";

const baseUrl = resolveApiBaseUrl();

export type UserNotification = {
  id: string;
  category: string;
  priority: string;
  title: string;
  body: string;
  action_url?: string | null;
  status: string;
  read_at?: string | null;
  created_at: string;
  expires_at?: string | null;
  expired: boolean;
};

export type NotificationPreference = {
  category: string;
  channel: "in_app" | "email";
  enabled: boolean;
  frequency: "immediate" | "daily_digest" | "weekly_digest" | "disabled";
  quiet_hours_enabled: boolean;
  quiet_hours_start?: string | null;
  quiet_hours_end?: string | null;
  quiet_hours_timezone?: string | null;
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, { ...init, credentials: "include", headers });
  const payload = (await response.json()) as { data: T; error?: { message: string } };
  if (!response.ok) throw new Error(payload.error?.message ?? "Notification request failed");
  return payload.data;
}

export const notificationApi = {
  list: (query = "") =>
    request<{ items: UserNotification[]; total: number }>(`/account/notifications${query}`),
  unread: () => request<{ count: number }>("/account/notifications/unread-count"),
  read: (id: string) => request(`/account/notifications/${id}/read`, { method: "POST" }),
  markAllRead: () => request<{ updated: number }>("/account/notifications/mark-all-read", { method: "POST" }),
  archive: (id: string) => request(`/account/notifications/${id}/archive`, { method: "POST" }),
  preferences: () =>
    request<{ items: NotificationPreference[]; mandatory_categories: string[] }>(
      "/account/notification-preferences"
    ),
  updatePreferences: (items: NotificationPreference[]) =>
    request<{ updated: number }>("/account/notification-preferences", {
      method: "PUT",
      body: JSON.stringify({ items })
    }),
  consents: () =>
    request<{ items: Array<{ consent_type: string; status: string; consent_version: string }> }>(
      "/account/notification-consents"
    ),
  setMarketingConsent: (granted: boolean) =>
    request(`/account/notification-consents/marketing_email/${granted ? "grant" : "withdraw"}`, {
      method: "POST",
      body: JSON.stringify({ consent_version: "2026-08-batch-11", evidence: { surface: "account" } })
    }),
  unsubscribePreview: (token: string) =>
    request<{ valid: boolean; category?: string; channel?: string }>(
      `/public/notifications/unsubscribe/${encodeURIComponent(token)}`
    ),
  unsubscribe: (token: string) =>
    request<{ status: string; category: string; channel: string }>(
      `/public/notifications/unsubscribe/${encodeURIComponent(token)}`,
      { method: "POST" }
    )
};
