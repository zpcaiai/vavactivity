import { useAuthStore } from "@/stores/auth";

import type {
  BatchRequestPayload,
  BatchRequestResult,
  ExposurePayload,
  ExposureResult,
  FeedbackPayload,
  FeedbackResult,
  RecommendationFeed,
  RecommendationHistory,
  RecommendationItem,
  RecommendationPreferences,
  RecommendationTransparencyData,
  SettingsUpdatePayload,
  SettingsUpdateResult,
  TuningResetResult,
  TuningUpdatePayload,
  TuningUpdateResult
} from "@/features/recommendations/types";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export async function recommendationApi<T>(path: string, init: RequestInit = {}): Promise<T> {
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
    const error = new Error(payload.error?.message ?? "推荐服务请求失败");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

export const recommendationsApi = {
  /** Today's list for this viewer: eligibility, batch, items and empty state. */
  list: () => recommendationApi<RecommendationFeed>("/recommendations"),
  /** Repeat calls return the existing batch; refreshing never buys extra recommendations. */
  requestBatch: (payload: BatchRequestPayload) =>
    recommendationApi<BatchRequestResult>("/recommendations/batches", {
      method: "POST",
      body: JSON.stringify({
        batch_type: payload.batch_type,
        requested_size: payload.requested_size ?? null
      })
    }),
  get: (itemId: string) =>
    recommendationApi<RecommendationItem>(`/recommendations/${encodeURIComponent(itemId)}`),
  recordExposure: (itemId: string, payload: ExposurePayload) =>
    recommendationApi<ExposureResult>(
      `/recommendations/${encodeURIComponent(itemId)}/exposures`,
      {
        method: "POST",
        body: JSON.stringify({
          exposure_type: payload.exposure_type,
          duration_ms: payload.duration_ms ?? null,
          source: payload.source ?? "recommendation_list"
        })
      }
    ),
  /** Only impression / viewed / profile_opened / not_relevant are accepted here. */
  submitFeedback: (itemId: string, payload: FeedbackPayload) =>
    recommendationApi<FeedbackResult>(`/recommendations/${encodeURIComponent(itemId)}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        feedback_type: payload.feedback_type,
        reason_code: payload.reason_code ?? null,
        reason_details: payload.reason_details ?? null
      })
    }),
  preferences: () => recommendationApi<RecommendationPreferences>("/account/recommendation-preferences"),
  savePreferences: (payload: SettingsUpdatePayload) =>
    recommendationApi<SettingsUpdateResult>("/account/recommendation-preferences", {
      method: "PUT",
      body: JSON.stringify(payload)
    }),
  saveTuning: (payload: TuningUpdatePayload) =>
    recommendationApi<TuningUpdateResult>("/account/recommendation-tuning", {
      method: "PUT",
      body: JSON.stringify(payload)
    }),
  resetTuning: () =>
    recommendationApi<TuningResetResult>("/account/recommendation-tuning/reset", {
      method: "POST"
    }),
  history: () => recommendationApi<RecommendationHistory>("/account/recommendation-history"),
  transparency: () =>
    recommendationApi<RecommendationTransparencyData>("/account/recommendation-transparency")
};
