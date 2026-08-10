/**
 * Types for the member-facing recommendation surface (Batch 14).
 *
 * The backend deliberately omits every score, percentage and directional
 * signal. Nothing in this file may introduce one: there is no compatibility
 * score type, and the front end never computes or infers one.
 */

export type ExplanationEntry = {
  explanation_code: string;
  display_text: string;
};

export type RecommendationExplanation = {
  summary: string;
  mutual_strengths: ExplanationEntry[];
  relevant_preferences: ExplanationEntry[];
  topics_to_explore: ExplanationEntry[];
  information_gaps: ExplanationEntry[];
  /** Shown verbatim; the front end never rewrites or softens the caveat. */
  caveat: string;
  relaxation_notices: string[];
  explanation_policy_version?: string | null;
};

export type RecommendationPhoto = {
  photo_id: string;
  status: string;
  requires_view_token: boolean;
};

/**
 * The frozen card snapshot the viewer is allowed to see.
 *
 * Only approved, city-level, non-contact information appears here. Exact birth
 * dates, contact details and the other member's own preference list are never
 * part of this payload.
 */
export type RecommendationProfile = {
  profile_id?: string;
  display_name?: string;
  age?: number | string | null;
  age_display?: string | null;
  city_code?: string | null;
  city_display?: string | null;
  region_code?: string | null;
  country_code?: string | null;
  relationship_intent?: string | null;
  primary_photo?: RecommendationPhoto | null;
  short_introduction?: string | null;
  self_introduction?: string | null;
  sections?: Record<string, unknown> | null;
};

export type RecommendationItemStatus =
  | "ready"
  | "exposed"
  | "viewed"
  | "expired"
  | "invalidated"
  | string;

export type RecommendationItem = {
  recommendation_item_id: string;
  rank_position: number;
  status: RecommendationItemStatus;
  profile: RecommendationProfile;
  explanation: RecommendationExplanation;
  available_from: string | null;
  expires_at: string | null;
};

export type RecommendationBatch = {
  batch_id: string;
  batch_number: number;
  batch_type: string;
  status: string;
  generated_size: number;
  expires_at: string | null;
};

export type RestrictiveCriterion = {
  criterion_code: string;
  excluded_count: number;
};

export type ColdStartState = {
  types: string[];
  exploration_slots: number;
  uses_platform_defaults: boolean;
  guidance_codes: string[];
  policy_version?: string;
};

export type RecommendationEmptyStateData = {
  available_actions: string[];
  /** Criterion codes with counts only — never a member identity. */
  most_restrictive_criteria: RestrictiveCriterion[];
  cold_start: ColdStartState | null;
};

export type RecommendationFeed = {
  eligible: boolean;
  ineligible_reason_codes: string[];
  recommendations_paused: boolean;
  batch: RecommendationBatch | null;
  items: RecommendationItem[];
  empty_state: RecommendationEmptyStateData | null;
};

export type BatchRequestPayload = {
  batch_type: "daily" | "supplemental";
  requested_size?: number | null;
};

export type BatchRequestResult = {
  batch_id: string;
  batch_type: string;
  status: string;
  generated_size: number;
  expires_at: string | null;
};

export type ExposureType = "card_impression" | "card_visible" | "profile_opened" | "photo_viewed";

export type ExposurePayload = {
  exposure_type: ExposureType;
  duration_ms?: number | null;
  source?: string;
};

export type ExposureResult = {
  recorded: boolean;
  reason_code?: string;
  counted_as_visible?: boolean;
  exposure_sequence?: number;
};

/** Likes and skips belong to Batch 15; this surface accepts viewing signals only. */
export type FeedbackType = "impression" | "viewed" | "profile_opened" | "not_relevant";

export type FeedbackPayload = {
  feedback_type: FeedbackType;
  reason_code?: string | null;
  reason_details?: string | null;
};

export type FeedbackResult = {
  feedback_id?: string;
  accepted?: boolean;
  [key: string]: unknown;
};

export type RecommendationSettings = {
  recommendations_paused: boolean;
  daily_received_limit: number | null;
  delivery_frequency: "daily" | "weekly" | "manual" | string;
  extended_recommendations_enabled: boolean;
  relaxable_criteria: string[];
  preferred_locale: string;
};

export type RecommendationTuning = {
  exploration_level: "conservative" | "balanced" | "adventurous" | string;
  feedback_personalization_enabled: boolean;
  adjusted_feature_count: number;
};

export type RecommendationPreferences = {
  settings: RecommendationSettings;
  tuning: RecommendationTuning;
  maximum_daily_received: number;
  feedback_reason_codes: string[];
};

export type SettingsUpdatePayload = {
  recommendations_paused?: boolean;
  daily_received_limit?: number;
  delivery_frequency?: string;
  extended_recommendations_enabled?: boolean;
  relaxable_criteria?: string[];
  preferred_locale?: string;
};

export type SettingsUpdateResult = RecommendationSettings & { settings_version: number };

export type TuningUpdatePayload = {
  feedback_personalization_enabled?: boolean;
  exploration_level?: string;
};

export type TuningUpdateResult = {
  exploration_level: string;
  feedback_personalization_enabled: boolean;
  tuning_version: number;
};

export type TuningResetResult = {
  tuning_version: number;
  adjusted_feature_count: number;
};

export type HistoryBatch = {
  batch_id: string;
  batch_number: number;
  batch_type: string;
  status: string;
  generated_size: number;
  created_at: string | null;
  expires_at: string | null;
};

export type RecommendationHistory = {
  batches: HistoryBatch[];
};

export type TransparencyFeature = {
  feature_group: string;
  feature_code: string;
  /** "your_stated_preference" or "platform_default". */
  source: string;
  user_configurable: boolean;
  your_information_available: boolean | null;
};

export type RecommendationTransparencyData = {
  data_categories_used: string[];
  features: TransparencyFeature[];
  hard_constraints_from_you: string[];
  never_used: string[];
  behavioural_personalization_enabled: boolean;
  how_to_adjust: string[];
};
