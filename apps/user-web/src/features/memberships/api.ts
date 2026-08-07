import { useAuthStore } from "@/stores/auth";
import { resolveApiBaseUrl } from "@/config/api";

const baseUrl = resolveApiBaseUrl();

export type MembershipPlan = {
  id: string;
  plan_code: string;
  plan_type: string;
  name: string;
  short_description?: string;
  benefits?: Array<{ benefit_code: string; benefit_type: string; benefit_value: Record<string, unknown> }>;
};

export type MembershipSummary = {
  membership_account_id: string;
  plan_code: string;
  plan_name: string;
  status: string;
  starts_at: string;
  expires_at?: string;
  current_cycle_ends_at?: string;
  cancel_at_period_end: boolean;
  benefits: Array<{ benefit_code: string; benefit_type: string; benefit_value: Record<string, unknown> }>;
  quotas: Array<{ id: string; benefit_code: string; allocated_quantity: number; consumed_quantity: number; reserved_quantity: number; remaining_quantity: number }>;
};

async function call<T>(path: string, init: RequestInit = {}, authenticated = false): Promise<T> {
  const headers = new Headers(init.headers);
  if (authenticated) {
    const auth = useAuthStore();
    await auth.bootstrap();
    if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  }
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, credentials: "include" });
  const payload = (await response.json()) as { data: T; error?: { message?: string; code?: string } };
  if (!response.ok) {
    const error = new Error(payload.error?.message ?? "会员请求失败");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

export const membershipApi = {
  plans: (locale: string) => call<MembershipPlan[]>(`/public/membership-plans?locale=${encodeURIComponent(locale)}`),
  plan: (code: string, locale: string) => call<MembershipPlan>(`/public/membership-plans/${encodeURIComponent(code)}?locale=${encodeURIComponent(locale)}`),
  current: () => call<MembershipSummary>("/account/membership", {}, true),
  history: () => call<Array<Record<string, unknown>>>("/account/membership/history", {}, true),
  preview: (toPlanCode: string, changeType: string) => call<Record<string, unknown>>("/account/membership/change-preview", { method: "POST", body: JSON.stringify({ to_plan_code: toPlanCode, change_type: changeType }) }, true),
  requestChange: (toPlanCode: string, changeType: string) => call<Record<string, unknown>>("/account/membership/change-requests", { method: "POST", body: JSON.stringify({ to_plan_code: toPlanCode, change_type: changeType, idempotency_key: `membership-change-${crypto.randomUUID()}` }) }, true),
  confirmChange: (id: string, version: number) => call<Record<string, unknown>>(`/account/membership/change-requests/${encodeURIComponent(id)}/confirm`, { method: "POST", body: JSON.stringify({ expected_version: version }) }, true)
};

export const membershipApiForTests = { call };
