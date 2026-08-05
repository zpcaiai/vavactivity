import { useAuthStore } from "@/stores/auth";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export type RelationshipRow = Record<string, unknown> & {
  journey_id?: string;
  status?: string;
  current_stage_code?: string;
  proposal_id?: string;
  pause_id?: string;
  version?: number;
};

async function relationshipApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, credentials: "include" });
  const payload = (await response.json()) as { data: T; error?: { message?: string; code?: string } };
  if (!response.ok) {
    const error = new Error(payload.error?.message ?? "关系旅程请求失败");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

function write<T>(path: string, operation: string, body?: unknown, method = "POST") {
  return relationshipApi<T>(path, {
    method,
    headers: { "Idempotency-Key": `${operation}-${crypto.randomUUID()}` },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
}

export const relationshipsApi = {
  list: () => relationshipApi<RelationshipRow[]>("/account/relationships"),
  detail: (id: string) => relationshipApi<RelationshipRow>(`/account/relationships/${encodeURIComponent(id)}`),
  timeline: (id: string) => relationshipApi<RelationshipRow[]>(`/account/relationships/${encodeURIComponent(id)}/timeline`),
  proposals: (id: string) => relationshipApi<RelationshipRow[]>(`/account/relationships/${encodeURIComponent(id)}/stage-proposals`),
  proposeStage: (id: string, stage: string, message?: string) => write<RelationshipRow>(`/account/relationships/${encodeURIComponent(id)}/stage-proposals`, "stage-proposal", { to_stage_code: stage, message: message || null }),
  decideProposal: (id: string, action: "accept" | "decline" | "cancel", version?: number) => write<RelationshipRow>(`/account/relationship-stage-proposals/${encodeURIComponent(id)}/${action}`, `proposal-${action}`, action === "cancel" ? undefined : { expected_version: version ?? null }),
  pause: (id: string, privateReason?: string, visibleMessage?: string) => write<RelationshipRow>(`/account/relationships/${encodeURIComponent(id)}/pause`, "pause", { private_reason: privateReason || null, visible_message: visibleMessage || null }),
  requestResume: (id: string) => write<RelationshipRow>(`/account/relationships/${encodeURIComponent(id)}/resume-request`, "resume-request", {}),
  decideResume: (pauseId: string, accept: boolean, version?: number) => write<RelationshipRow>(`/account/relationship-pauses/${encodeURIComponent(pauseId)}/${accept ? "accept-resume" : "decline-resume"}`, `resume-${accept ? "accept" : "decline"}`, { expected_version: version ?? null }),
  end: (id: string, reasonCode?: string, privateReason?: string, visibleMessage?: string) => write<RelationshipRow>(`/account/relationships/${encodeURIComponent(id)}/end`, "end", { confirmed: true, reason_code: reasonCode || null, private_reason: privateReason || null, visible_message: visibleMessage || null }),
  milestones: (id: string) => relationshipApi<RelationshipRow[]>(`/account/relationships/${encodeURIComponent(id)}/milestones`),
  createMilestone: (id: string, payload: Record<string, unknown>) => write<RelationshipRow>(`/account/relationships/${encodeURIComponent(id)}/milestones`, "milestone", payload),
  checkin: (id: string, responses: Record<string, unknown>, visibility = "private") => write<RelationshipRow>(`/account/relationships/${encodeURIComponent(id)}/checkins`, "checkin", { responses, visibility }),
  reflections: (id: string) => relationshipApi<RelationshipRow[]>(`/account/relationships/${encodeURIComponent(id)}/reflections`),
  reflect: (id: string, reflection: string) => write<RelationshipRow>(`/account/relationships/${encodeURIComponent(id)}/reflections`, "reflection", { reflection, ai_processing_consent_id: null })
};

export const relationshipApiForTests = { relationshipApi };
