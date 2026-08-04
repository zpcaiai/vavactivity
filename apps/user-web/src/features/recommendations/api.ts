import { useAuthStore } from "@/stores/auth";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export type ExplanationItem = {
  explanation_code: string;
  display_text: string;
  source_feature_codes: string[];
  confidence_bps: number;
  disclosure_level: string;
};

export type RecommendationExplanation = {
  summary: string;
  mutual_strengths: ExplanationItem[];
  relevant_preferences: ExplanationItem[];
  topics_to_explore: ExplanationItem[];
  information_gaps: ExplanationItem[];
  /** Always shown: a recommendation is an opportunity, not a promise. */
  caveat: string;
  explanation_policy_version: string;
};

/** The de-identified summary a card may show. No name, photo or contact detail. */
export type ProfileSummary = {
  age_bucket?: string | null;
  city_code?: string | null;
  region_code?: string | null;
  country_code?: string | null;
  faith_codes?: string[];
  language_codes?: string[];
  lifestyle_codes?: string[];
  relationship_intent?: string | null;
  marital_status_code?: string | null;
  children_status_code?: string | null;
  relocation_willingness?: string | null;
};

export type RecommendationItem = {
  recommendation_item_id: string;
  recommended_user_id: string;
  rank_position: number;
  status: string;
  is_exploration_slot: boolean;
  relaxation_applied: string[];
  explanation: RecommendationExplanation;
  profile_summary: ProfileSummary;
  available_from: string | null;
  expires_at: string | null;
};

export type EmptyGuidance = {
  message: string;
  largest_reductions: { criterion_code: string; excluded_candidates: number }[];
  options: string[];
  never_done: string[];
};

export type RecommendationBatch = {
  has_batch: boolean;
  batch_id?: string;
  batch_number?: number;
  batch_type?: string;
  expires_at?: string | null;
  items: RecommendationItem[];
  guidance: EmptyGuidance | null;
};

export type RecommendationPreferences = {
  exploration_level: string;
  feedback_personalization_enabled: boolean;
  daily_received_limit: number;
  maximum_daily_received_limit: number;
  allow_relaxed_recommendations: boolean;
  recommendations_paused: boolean;
  tuning_version: number;
  /** Things no setting can ever do, stated plainly to the member. */
  cannot_configure: string[];
};

export type Transparency = {
  data_categories_used: string[];
  your_explicit_preferences: string[];
  platform_default_soft_signals: string[];
  never_used: string[];
  how_to_adjust: string[];
  cannot_view: string[];
  feedback_personalization_enabled: boolean;
  preference_guidance: { needed: boolean; messages: string[]; mandatory_fields?: string[] };
  explanation_policy_version: string;
};

export type HistoryEntry = {
  id: string;
  recommended_user_id: string;
  rank_position: number;
  status: string;
  is_exploration_slot: boolean;
  created_at: string;
};

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
    const error = new Error(payload.error?.message ?? "推荐请求失败");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

function idempotencyKey(prefix: string): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${random}`;
}

export const recommendationsApi = {
  current: () => recommendationApi<RecommendationBatch>("/recommendations"),
  generate: (requestedSize?: number) =>
    recommendationApi<{ batch_id: string; size: number; status: string }>(
      "/recommendations/batches",
      { method: "POST", body: JSON.stringify({ batch_type: "daily", requested_size: requestedSize }) }
    ),
  detail: (itemId: string) =>
    recommendationApi<RecommendationItem & { dating_profile_endpoint: string; available_actions: string[] }>(
      `/recommendations/${itemId}`
    ),
  recordExposure: (itemId: string, exposureType: string, durationMs?: number) =>
    recommendationApi<{ recorded: boolean; duplicate: boolean; counted_as_visible: boolean }>(
      `/recommendations/${itemId}/exposure`,
      {
        method: "POST",
        body: JSON.stringify({
          exposure_type: exposureType,
          duration_ms: durationMs ?? null,
          idempotency_key: idempotencyKey(exposureType),
          source: "user_web"
        })
      }
    ),
  sendFeedback: (payload: {
    recommended_user_id: string;
    feedback_type: string;
    reason_code?: string | null;
    reason_details?: string | null;
    recommendation_item_id?: string | null;
  }) =>
    recommendationApi<{ recorded: boolean; used_for_learning: boolean; removed_from_candidates: boolean }>(
      "/recommendations/feedback",
      {
        method: "POST",
        body: JSON.stringify({ ...payload, idempotency_key: idempotencyKey("feedback") })
      }
    ),
  preferences: () => recommendationApi<RecommendationPreferences>("/account/recommendation-preferences"),
  savePreferences: (payload: Partial<RecommendationPreferences>) =>
    recommendationApi<RecommendationPreferences>("/account/recommendation-preferences", {
      method: "PUT",
      body: JSON.stringify(payload)
    }),
  resetPreferences: () =>
    recommendationApi<{ reset: boolean }>("/account/recommendation-preferences/reset", {
      method: "POST"
    }),
  history: (page = 1, pageSize = 20) =>
    recommendationApi<{ items: HistoryEntry[]; page: number; page_size: number; total: number }>(
      `/account/recommendation-history?page=${page}&page_size=${pageSize}`
    ),
  transparency: () => recommendationApi<Transparency>("/account/recommendation-transparency")
};

/** Skip reasons a member may choose. "Prefer not to say" is always available. */
export const SKIP_REASONS: { code: string; label: string }[] = [
  { code: "location_not_suitable", label: "地点不合适" },
  { code: "faith_expectations_differ", label: "信仰期待不同" },
  { code: "relationship_goal_differs", label: "关系目标不同" },
  { code: "family_or_children_expectations_differ", label: "家庭或生育期待不同" },
  { code: "lifestyle_not_suitable", label: "生活方式不合适" },
  { code: "profile_too_sparse", label: "资料太少，难以判断" },
  { code: "not_looking_right_now", label: "我暂时不想认识新的人" },
  { code: "prefer_not_to_say", label: "不想说明原因" }
];

export const EXPLORATION_LEVELS: { code: string; label: string; description: string }[] = [
  { code: "focused", label: "更聚焦", description: "更严格地贴近你设置的条件" },
  { code: "balanced", label: "平衡", description: "在你的条件之外保留少量探索位" },
  { code: "open", label: "更开放", description: "保留更多探索位，仍然遵守你的硬性条件" }
];
