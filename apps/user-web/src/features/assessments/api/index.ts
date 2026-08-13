import { resolveApiBaseUrl } from "@/config/api";
import type {
  AssessmentReport,
  Attempt,
  AttemptSaveResult,
  CatalogueEntry,
  Entitlement,
  PurchaseResult
} from "@/features/assessments/types";
import { useAuthStore } from "@/stores/auth";

const baseUrl = resolveApiBaseUrl();

export async function assessmentsApi<T>(path: string, init: RequestInit = {}): Promise<T> {
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
    const error = new Error(payload.error?.message ?? "assessment request failed");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

export const assessmentsApiClient = {
  catalogue(): Promise<{ items: CatalogueEntry[] }> {
    return assessmentsApi<{ items: CatalogueEntry[] }>("/account/assessments/catalogue");
  },

  /**
   * `quoted_price_minor_units` is the price the member was shown. The server
   * compares it against the version's real price and refuses a mismatch, so
   * this must be the displayed figure — never re-read from the catalogue at
   * submit time.
   */
  purchase(payload: {
    version_id: string;
    order_id: string;
    quoted_price_minor_units: number;
  }): Promise<PurchaseResult> {
    return assessmentsApi<PurchaseResult>("/account/assessments/purchases", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  entitlements(): Promise<{ items: Entitlement[] }> {
    return assessmentsApi<{ items: Entitlement[] }>("/account/assessments/entitlements");
  },

  startAttempt(entitlementId: string): Promise<{ attempt_id: string; status: string; version_id: string; created: boolean }> {
    return assessmentsApi(`/account/assessments/entitlements/${entitlementId}/attempts`, {
      method: "POST",
      body: JSON.stringify({})
    });
  },

  attempt(attemptId: string): Promise<Attempt> {
    return assessmentsApi<Attempt>(`/account/assessments/attempts/${attemptId}`);
  },

  saveAnswers(
    attemptId: string,
    payload: { answers: Record<string, number>; submit: boolean }
  ): Promise<AttemptSaveResult> {
    return assessmentsApi<AttemptSaveResult>(
      `/account/assessments/attempts/${attemptId}/answers`,
      { method: "PUT", body: JSON.stringify(payload) }
    );
  },

  report(attemptId: string): Promise<AssessmentReport> {
    return assessmentsApi<AssessmentReport>(`/account/assessments/attempts/${attemptId}/report`);
  }
};
