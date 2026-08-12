import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { VBreadcrumbItem, VTabItem } from "@vav/ui-core";

import { useLocalePath } from "@/composables/useAppNavigation";
import {
  datingProfileApi,
  type Completeness,
  type DatingProfile,
  type FieldDefinition,
  type PreferenceState,
  type PrivacyState,
  type ProfilePhoto,
  type ProfileSchema,
  type ReviewFeedback,
  type ViewProjection
} from "@/features/dating-profile/api";

export type ProfileStepKey =
  | "overview"
  | "edit"
  | "photos"
  | "preferences"
  | "privacy"
  | "preview"
  | "review";

/** Structured sections rendered inside the edit step, in filling order. */
export const FIELD_GROUPS: { key: string; sections: string[] }[] = [
  { key: "basic", sections: ["basic", "location", "education_and_work"] },
  { key: "faith", sections: ["faith"] },
  { key: "history", sections: ["relationship_history"] },
  { key: "family", sections: ["family", "children_and_parenting"] },
  { key: "lifestyle", sections: ["lifestyle", "interests", "communication"] },
  { key: "narratives", sections: [] }
];

export const NARRATIVE_FIELDS = [
  "self_introduction",
  "faith_journey",
  "relationship_values",
  "marriage_vision",
  "family_vision",
  "strengths_and_growth",
  "interests_and_lifestyle",
  "hoped_for_relationship"
] as const;

export const PREVIEW_CONTEXTS = [
  "recommendation_card",
  "profile_detail",
  "activity_directory",
  "mutual_match"
] as const;

export const VISIBILITY_OPTIONS = ["private", "mutual_only", "verified_members"] as const;

const STEP_PATHS: Record<ProfileStepKey, string> = {
  overview: "account/dating-profile",
  edit: "account/dating-profile/edit",
  photos: "account/dating-profile/photos",
  preferences: "account/dating-profile/preferences",
  privacy: "account/dating-profile/privacy",
  preview: "account/dating-profile/preview",
  review: "account/dating-profile/review"
};

/*
 * Module-scoped state: the profile wizard spans seven routes and every step
 * needs the same schema, draft values and completeness. Re-fetching all six
 * endpoints on each step — as the single-page version did — made every step
 * change feel like a cold start.
 */
const profile = ref<DatingProfile>();
const schema = ref<ProfileSchema>();
const completeness = ref<Completeness>();
const photos = ref<ProfilePhoto[]>([]);
const preferences = ref<PreferenceState>();
const privacy = ref<PrivacyState>();
const feedback = ref<ReviewFeedback>();
const preview = ref<ViewProjection>();
const fieldValues = reactive<Record<string, unknown>>({});
const narrativeValues = reactive<Record<string, string>>({});
const loaded = ref(false);

export function useDatingProfile() {
  const { t } = useI18n();
  const { localePath, locale } = useLocalePath();

  const busy = ref(false);
  const error = ref("");
  const notice = ref("");

  const completionPercent = computed(() =>
    Math.round((completeness.value?.total_basis_points ?? 0) / 100)
  );
  const missingRequired = computed(() => completeness.value?.missing_required_fields ?? []);
  const canSubmit = computed(() => completeness.value?.submission_eligible === true);
  const exists = computed(() => profile.value?.exists === true);

  const steps = computed<VTabItem[]>(() =>
    (Object.keys(STEP_PATHS) as ProfileStepKey[]).map((key) => ({
      key,
      label: t(`dating.steps.${key}`),
      to: localePath(STEP_PATHS[key])
    }))
  );

  function breadcrumbs(current: ProfileStepKey): VBreadcrumbItem[] {
    return [
      { label: t("ia.groups.matchmaking"), to: localePath("recommendations") },
      { label: t("dating.title"), to: localePath(STEP_PATHS.overview) },
      { label: t(`dating.steps.${current}`) }
    ];
  }

  async function guard<T>(action: () => Promise<T>, successMessage?: string): Promise<T | undefined> {
    busy.value = true;
    error.value = "";
    try {
      const result = await action();
      if (successMessage) notice.value = successMessage;
      return result;
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "";
      return undefined;
    } finally {
      busy.value = false;
    }
  }

  async function refreshProfile() {
    const [current, completenessValue] = await Promise.all([
      datingProfileApi.get(),
      datingProfileApi.completeness()
    ]);
    profile.value = current;
    completeness.value = completenessValue;
  }

  /** Loads once per session unless `force` is set; safe to call from any step. */
  async function ensureLoaded(force = false) {
    if (loaded.value && !force) return;
    await guard(async () => {
      const current = await datingProfileApi.get();
      profile.value = current;
      loaded.value = true;
      if (!current.exists) return;
      const [schemaValue, completenessValue, photoValue, preferenceValue, privacyValue, feedbackValue] =
        await Promise.all([
          datingProfileApi.schema(locale.value),
          datingProfileApi.completeness(),
          datingProfileApi.photos(),
          datingProfileApi.preferences(),
          datingProfileApi.privacy(),
          datingProfileApi.reviewFeedback()
        ]);
      schema.value = schemaValue;
      completeness.value = completenessValue;
      photos.value = photoValue.items;
      preferences.value = preferenceValue;
      privacy.value = privacyValue;
      feedback.value = feedbackValue;
      for (const [key, value] of Object.entries(current.projection?.visible_fields ?? {})) {
        fieldValues[key] = value;
      }
    });
  }

  async function createProfile() {
    await guard(() => datingProfileApi.create(locale.value), t("dating.created"));
    await ensureLoaded(true);
  }

  function fieldsForGroup(groupKey: string): FieldDefinition[] {
    const group = FIELD_GROUPS.find((item) => item.key === groupKey);
    if (!group || !schema.value || !group.sections.length) return [];
    return schema.value.fields
      .filter((field) => group.sections.includes(field.section_code))
      .sort((a, b) => b.weight - a.weight);
  }

  function taxonomyFor(field: FieldDefinition) {
    const code = field.value_schema.taxonomy as string | undefined;
    if (!code || !schema.value) return [];
    return (schema.value.taxonomies[code]?.values ?? []).filter((value) => value.enabled);
  }

  async function saveFields(fields: FieldDefinition[]) {
    const payload: Record<string, unknown> = {};
    for (const field of fields) {
      const value = fieldValues[field.field_code];
      if (value !== undefined) payload[field.field_code] = value;
    }
    if (!Object.keys(payload).length) {
      notice.value = t("dating.nothingToSave");
      return;
    }
    const result = await guard(
      () => datingProfileApi.patchFields(payload, profile.value?.version),
      t("dating.sectionSaved")
    );
    if (result) completeness.value = result;
    await refreshProfile();
  }

  async function saveNarratives(aiAssisted: boolean, aiConfirmed: boolean) {
    const result = await guard(
      () =>
        datingProfileApi.putNarratives({
          locale: locale.value,
          ...narrativeValues,
          ai_assisted: aiAssisted,
          ai_content_confirmed: aiConfirmed
        }),
      t("dating.narrativesSaved")
    );
    if (result) completeness.value = result;
    await refreshProfile();
  }

  async function reloadPhotos() {
    const result = await guard(() => datingProfileApi.photos());
    if (result) photos.value = result.items;
  }

  async function savePreferences() {
    const current = preferences.value;
    if (!current) return;
    const result = await guard(
      () => datingProfileApi.savePreferences(current.criteria, current.allow_recommendation_relaxation),
      t("dating.preferencesSaved")
    );
    if (result) preferences.value = result;
    await refreshProfile();
  }

  async function savePrivacy() {
    const current = privacy.value;
    if (!current) return;
    const rules = Object.entries(current.field_visibility).map(([field_code, visibility]) => ({
      field_code,
      visibility
    }));
    await guard(
      () => datingProfileApi.savePrivacy(rules, current.visible_in_matchmaking),
      t("dating.privacySaved")
    );
    await refreshProfile();
  }

  async function loadPreview(context: string) {
    const result = await guard(() => datingProfileApi.preview(context));
    if (result) preview.value = result.preview;
  }

  async function submitForReview(changeSummary: string) {
    const result = await guard(() => datingProfileApi.submit(changeSummary));
    if (result) notice.value = t("dating.submitted", { version: result.version_number });
    await ensureLoaded(true);
  }

  async function setLifecycle(action: "pause" | "reactivate") {
    await guard(
      () => (action === "pause" ? datingProfileApi.pause() : datingProfileApi.reactivate()),
      t(action === "pause" ? "dating.paused" : "dating.reactivated")
    );
    await refreshProfile();
  }

  return {
    // state
    profile,
    schema,
    completeness,
    photos,
    preferences,
    privacy,
    feedback,
    preview,
    fieldValues,
    narrativeValues,
    busy,
    error,
    notice,
    // derived
    exists,
    completionPercent,
    missingRequired,
    canSubmit,
    steps,
    breadcrumbs,
    localePath,
    t,
    // actions
    guard,
    ensureLoaded,
    createProfile,
    fieldsForGroup,
    taxonomyFor,
    saveFields,
    saveNarratives,
    reloadPhotos,
    savePreferences,
    savePrivacy,
    loadPreview,
    submitForReview,
    setLifecycle
  };
}
