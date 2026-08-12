import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { VBreadcrumbItem, VTabItem } from "@vav/ui-core";

import { useLocalePath } from "@/composables/useAppNavigation";

export type SafetySectionKey = "overview" | "reports" | "blocks" | "restrictions" | "appeals";

const SECTION_PATHS: Record<SafetySectionKey, string> = {
  overview: "account/safety",
  reports: "account/safety/reports",
  blocks: "account/safety/blocks",
  restrictions: "account/safety/restrictions",
  appeals: "account/safety/appeals"
};

/** Report categories are a closed set; the backend rejects anything else. */
export const REPORT_CATEGORIES = [
  "harassment",
  "threat",
  "fraud_or_scam",
  "money_request",
  "impersonation",
  "underage_concern",
  "privacy_violation",
  "other"
] as const;

export function useSafetyShell(current: SafetySectionKey) {
  const { t } = useI18n();
  const { localePath } = useLocalePath();

  const sections = computed<VTabItem[]>(() =>
    (Object.keys(SECTION_PATHS) as SafetySectionKey[]).map((key) => ({
      key,
      label: t(`safety.sections.${key}`),
      to: localePath(SECTION_PATHS[key])
    }))
  );

  const breadcrumbs = computed<VBreadcrumbItem[]>(() => [
    { label: t("ia.groups.account"), to: localePath("account/profile") },
    { label: t("safety.title"), to: localePath("account/safety") },
    { label: t(`safety.sections.${current}`) }
  ]);

  return { sections, breadcrumbs, localePath, t };
}

export function useSafetyState() {
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
