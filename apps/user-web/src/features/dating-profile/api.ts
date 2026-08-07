import { useAuthStore } from "@/stores/auth";
import { resolveApiBaseUrl } from "@/config/api";

const baseUrl = resolveApiBaseUrl();

export type FieldDefinition = {
  field_code: string;
  section_code: string;
  field_type: string;
  value_schema: Record<string, unknown>;
  required_for_submission: boolean;
  required_for_recommendation: boolean;
  sensitivity: string;
  default_visibility: string;
  weight: number;
};

export type TaxonomyValue = { code: string; enabled: boolean; label: string };
export type Taxonomy = { semantic_version: string; values: TaxonomyValue[] };

export type ProfileSchema = {
  schema_code: string;
  semantic_version: string;
  sections: string[];
  fields: FieldDefinition[];
  completeness_policy: Record<string, unknown>;
  submission_policy: Record<string, unknown>;
  taxonomies: Record<string, Taxonomy>;
};

export type ViewProjection = {
  profile_id: string;
  profile_number: string;
  display_name: string;
  age_display: string | null;
  city_display: string | null;
  primary_photo: { photo_id: string; status: string; requires_view_token: boolean } | null;
  self_introduction: string | null;
  visible_fields: Record<string, unknown>;
  withheld_field_count: number;
  view_context: string;
  contact_exchange_status: string;
  contact_details_available: boolean;
  moderation_badges: string[];
};

export type DatingProfile = {
  exists: boolean;
  eligible_to_create?: boolean;
  profile_id?: string;
  profile_number?: string;
  status?: string;
  review_status?: string;
  version?: number;
  current_version_number?: number;
  approved_version_number?: number | null;
  default_locale?: string;
  completeness_basis_points?: number;
  projection?: ViewProjection;
};

export type Completeness = {
  policy_version: string;
  total_basis_points: number;
  section_scores: Record<string, number>;
  missing_required_fields: string[];
  missing_recommended_fields: string[];
  submission_eligible: boolean;
  recommendation_eligible: boolean;
  /** Always "form_completion_only" — never a measure of personal worth. */
  measures: string;
};

export type ProfilePhoto = {
  photo_id: string;
  photo_role: string;
  status: string;
  visibility: string;
  sort_order: number;
  quality_flags: string[];
  exif_removed: boolean;
  rejection_reason_code: string | null;
  rejection_message_safe: string | null;
  created_at: string;
};

export type PreferenceCriterion = {
  criterion_code: string;
  operator: string;
  desired_value: unknown;
  importance: string;
  hard_constraint: boolean;
  allow_unknown: boolean;
  allow_system_relaxation: boolean;
  user_explanation: string | null;
};

export type PreferenceState = {
  criteria: PreferenceCriterion[];
  hard_constraints: { criterion_code: string; excludes_unknown_values: boolean; may_be_relaxed_by_system: boolean }[];
  preference_version: number;
  allow_recommendation_relaxation: boolean;
  status: string;
  visibility: string;
  approved_criteria: string[];
};

export type PrivacyState = {
  privacy_mode: string;
  visible_in_matchmaking: boolean;
  field_visibility: Record<string, string>;
  contact_details_ever_public: boolean;
  ai_profile_access: boolean;
};

export type ReviewFeedback = {
  has_feedback: boolean;
  review_status?: string;
  overall_decision?: string;
  message?: string | null;
  version_number?: number;
  items: {
    item_type: string;
    field_code: string | null;
    photo_id: string | null;
    decision: string;
    reason_code: string | null;
    user_message_safe: string | null;
  }[];
};

export async function datingApi<T>(path: string, init: RequestInit = {}): Promise<T> {
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
    const error = new Error(payload.error?.message ?? "婚恋档案请求失败");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

export const datingProfileApi = {
  get: () => datingApi<DatingProfile>("/account/dating-profile"),
  create: (locale?: string) =>
    datingApi<{ profile_id: string; status: string }>("/account/dating-profile", {
      method: "POST",
      body: JSON.stringify({ locale })
    }),
  schema: (locale: string) =>
    datingApi<ProfileSchema>(`/account/dating-profile/schema?locale=${encodeURIComponent(locale)}`),
  patchFields: (values: Record<string, unknown>, expectedVersion?: number) =>
    datingApi<Completeness>("/account/dating-profile", {
      method: "PATCH",
      body: JSON.stringify({ values, expected_version: expectedVersion })
    }),
  putNarratives: (payload: Record<string, unknown>) =>
    datingApi<Completeness>("/account/dating-profile/narratives", {
      method: "PUT",
      body: JSON.stringify(payload)
    }),
  completeness: () => datingApi<Completeness>("/account/dating-profile/completeness"),
  photos: () => datingApi<{ items: ProfilePhoto[] }>("/account/dating-profile/photos"),
  uploadPhoto: (payload: {
    filename: string;
    mime_type: string;
    content_base64: string;
    photo_role: string;
  }) =>
    datingApi<{ photo_id: string; status: string; exif_removed: boolean; quality_flags: string[] }>(
      "/account/dating-profile/photos",
      { method: "POST", body: JSON.stringify(payload) }
    ),
  makePrimary: (photoId: string) =>
    datingApi<{ photo_id: string }>(`/account/dating-profile/photos/${photoId}/primary`, {
      method: "POST"
    }),
  deletePhoto: (photoId: string) =>
    datingApi<{ photo_id: string }>(`/account/dating-profile/photos/${photoId}`, {
      method: "DELETE"
    }),
  preferences: () => datingApi<PreferenceState>("/account/dating-profile/preferences"),
  savePreferences: (criteria: unknown[], allowRelaxation: boolean) =>
    datingApi<PreferenceState>("/account/dating-profile/preferences", {
      method: "PUT",
      body: JSON.stringify({ criteria, allow_recommendation_relaxation: allowRelaxation })
    }),
  privacy: () => datingApi<PrivacyState>("/account/dating-profile/privacy"),
  savePrivacy: (rules: { field_code: string; visibility: string }[], visibleInMatchmaking?: boolean) =>
    datingApi<{ updated_fields: number }>("/account/dating-profile/privacy", {
      method: "PUT",
      body: JSON.stringify({ rules, visible_in_matchmaking: visibleInMatchmaking })
    }),
  preview: (context: string) =>
    datingApi<{ preview: ViewProjection; is_draft_preview: boolean }>(
      `/account/dating-profile/preview?view_context=${encodeURIComponent(context)}`
    ),
  submit: (changeSummary: string) =>
    datingApi<{ version_number: number; status: string }>("/account/dating-profile/submit", {
      method: "POST",
      body: JSON.stringify({ change_summary: changeSummary })
    }),
  reviewStatus: () =>
    datingApi<{ status: string; review_status: string; approved_version_number: number | null }>(
      "/account/dating-profile/review-status"
    ),
  reviewFeedback: () => datingApi<ReviewFeedback>("/account/dating-profile/review-feedback"),
  pause: () => datingApi<{ status: string }>("/account/dating-profile/pause", { method: "POST" }),
  reactivate: () =>
    datingApi<{ status: string }>("/account/dating-profile/reactivate", { method: "POST" })
};
