import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { VBreadcrumbItem, VTabItem } from "@vav/ui-core";

import { useLocalePath } from "@/composables/useAppNavigation";

export type PrivacySectionKey = "profile" | "settings" | "consents" | "requests" | "memory";

export interface PrivacySettings {
  privacy_mode: "strict" | "balanced" | "custom";
  searchable_by_platform_users: boolean;
  visible_in_activity_directory: boolean;
  visible_in_matchmaking: boolean;
  allow_contact_exchange_after_mutual_confirmation: boolean;
  allow_profile_use_by_ai: boolean;
  allow_service_history_use_by_ai: boolean;
  settings_version: number;
  field_rules: unknown[];
}

export interface MemoryPreferences {
  long_term_memory_enabled: boolean;
  allow_profile_facts: boolean;
  allow_service_history: boolean;
  allow_relationship_context: boolean;
  allow_cross_conversation_use: boolean;
  settings_version: number;
}

const SECTION_PATHS: Record<PrivacySectionKey, string> = {
  profile: "account/profile",
  settings: "account/privacy",
  consents: "account/consents",
  requests: "account/privacy/requests",
  memory: "account/ai-memory"
};

export function usePrivacyShell(current: PrivacySectionKey) {
  const { t } = useI18n();
  const { localePath } = useLocalePath();

  const sections = computed<VTabItem[]>(() =>
    (Object.keys(SECTION_PATHS) as PrivacySectionKey[]).map((key) => ({
      key,
      label: t(`privacy.sections.${key}`),
      to: localePath(SECTION_PATHS[key])
    }))
  );

  const breadcrumbs = computed<VBreadcrumbItem[]>(() => [
    { label: t("ia.groups.account"), to: localePath("account/profile") },
    { label: t(`privacy.sections.${current}`) }
  ]);

  return { sections, breadcrumbs, localePath, t };
}

/**
 * Shared busy / error / notice handling. Each privacy page loads only the
 * endpoints it actually renders — the previous single-page version fetched all
 * six on every section, including the ones it was about to hide.
 */
export function usePrivacyState() {
  const busy = ref(false);
  const error = ref("");
  const notice = ref("");

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

  return { busy, error, notice, guard };
}
