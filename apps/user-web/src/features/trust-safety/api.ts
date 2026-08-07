import { useAuthStore } from "@/stores/auth";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export type SafetyReport = {
  id: string;
  report_number: string;
  reported_user_id?: string;
  target_type: string;
  category: string;
  status: string;
  block_requested: boolean;
  immediate_danger_claimed: boolean;
  submitted_at: string;
};

export type SafetyBlock = {
  id: string;
  blocked_user_id: string;
  reason_code?: string;
  created_at: string;
};

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers,
    credentials: "include"
  });
  const payload = (await response.json()) as {
    data: T;
    error?: { message?: string; code?: string };
  };
  if (!response.ok) {
    const error = new Error(payload.error?.message ?? "安全请求失败");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

export const safetyApi = {
  reports: () => call<SafetyReport[]>("/account/safety/reports"),
  report: (payload: Record<string, unknown>) =>
    call<SafetyReport>("/safety/reports", { method: "POST", body: JSON.stringify(payload) }),
  withdrawReport: (id: string) =>
    call<SafetyReport>(`/account/safety/reports/${encodeURIComponent(id)}/withdraw`, {
      method: "POST"
    }),
  uploadEvidence: (reportId: string, payload: Record<string, unknown>) =>
    call<Record<string, unknown>>(`/account/safety/reports/${encodeURIComponent(reportId)}/evidence`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  blocks: () => call<SafetyBlock[]>("/account/safety/blocks"),
  block: (userId: string, reasonCode?: string) =>
    call<Record<string, unknown>>(`/safety/blocks/${encodeURIComponent(userId)}`, {
      method: "POST",
      body: JSON.stringify({ reason_code: reasonCode })
    }),
  unblock: (userId: string) =>
    call<Record<string, unknown>>(`/safety/blocks/${encodeURIComponent(userId)}`, {
      method: "DELETE"
    }),
  restrictions: () => call<Record<string, unknown>>("/account/safety/restrictions"),
  appeals: () => call<Array<Record<string, unknown>>>("/account/safety/appeals"),
  appeal: (restrictionId: string, reason: string) =>
    call<Record<string, unknown>>("/account/safety/appeals", {
      method: "POST",
      body: JSON.stringify({ restriction_id: restrictionId, reason, evidence_manifest: [] })
    })
};

export const safetyApiForTests = { call };
