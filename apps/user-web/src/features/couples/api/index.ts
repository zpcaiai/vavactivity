import { resolveApiBaseUrl } from "@/config/api";
import type {
  CoupleInvitation,
  CoupleRelationship,
  RelationshipKind,
  ScopeAssessment,
  ScopeReport,
  ScopeSaveResult,
  ScopeStartResult,
  ScopeVersion
} from "@/features/couples/types";
import { useAuthStore } from "@/stores/auth";

const baseUrl = resolveApiBaseUrl();

export async function couplesApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, credentials: "include" });
  const payload = (await response.json()) as {
    data: T;
    error?: { message: string; code?: string; details?: unknown[] };
  };
  if (!response.ok) {
    const error = new Error(payload.error?.message ?? "couples request failed");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

export const couplesApiClient = {
  createInvitation(payload: {
    invitee_user_id: string;
    relationship_kind: RelationshipKind;
    note?: string | null;
  }): Promise<{ invitation_id: string; status: string; relationship_kind: string; expires_at: string | null }> {
    return couplesApi("/account/couple/invitations", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  invitations(): Promise<{ items: CoupleInvitation[] }> {
    return couplesApi<{ items: CoupleInvitation[] }>("/account/couple/invitations");
  },

  respond(invitationId: string, decision: "accept" | "reject"): Promise<Record<string, unknown>> {
    return couplesApi(`/account/couple/invitations/${invitationId}/response`, {
      method: "POST",
      body: JSON.stringify({ decision })
    });
  },

  cancel(invitationId: string): Promise<Record<string, unknown>> {
    return couplesApi(`/account/couple/invitations/${invitationId}/cancellation`, {
      method: "POST",
      body: JSON.stringify({})
    });
  },

  relationship(): Promise<CoupleRelationship> {
    return couplesApi<CoupleRelationship>("/account/couple/relationship");
  },

  unbind(reason: string): Promise<Record<string, unknown>> {
    return couplesApi("/account/couple/relationship/unbind", {
      method: "POST",
      body: JSON.stringify({ reason })
    });
  },

  scopeVersions(): Promise<{ items: ScopeVersion[] }> {
    return couplesApi<{ items: ScopeVersion[] }>("/account/couple/scope/versions");
  },

  /**
   * `version_id` is explicit rather than "current": a pair that starts an
   * assessment finishes it on the version they started (SCOPE-001).
   */
  startAssessment(versionId: string): Promise<ScopeStartResult> {
    return couplesApi<ScopeStartResult>("/account/couple/scope/assessments", {
      method: "POST",
      body: JSON.stringify({ version_id: versionId })
    });
  },

  assessment(assessmentId: string): Promise<ScopeAssessment> {
    return couplesApi<ScopeAssessment>(`/account/couple/scope/assessments/${assessmentId}`);
  },

  /**
   * Raw answers are sealed per owner. Calling this with anyone else's id is a
   * 403 by design — do not build a UI that offers it.
   */
  myAnswers(assessmentId: string, ownerId: string): Promise<{ answers: Record<string, number> }> {
    return couplesApi<{ answers: Record<string, number> }>(
      `/account/couple/scope/assessments/${assessmentId}/answers/${ownerId}`
    );
  },

  saveAnswers(
    assessmentId: string,
    payload: { answers: Record<string, number>; submit: boolean }
  ): Promise<ScopeSaveResult> {
    return couplesApi<ScopeSaveResult>(
      `/account/couple/scope/assessments/${assessmentId}/answers`,
      { method: "PUT", body: JSON.stringify(payload) }
    );
  },

  report(assessmentId: string): Promise<ScopeReport> {
    return couplesApi<ScopeReport>(`/account/couple/scope/assessments/${assessmentId}/report`);
  }
};
