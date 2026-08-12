import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { VBreadcrumbItem, VTabItem } from "@vav/ui-core";

import { useLocalePath } from "@/composables/useAppNavigation";
import type { MembershipSummary } from "@/features/memberships/api";

export type MembershipSectionKey = "overview" | "benefits" | "usage" | "manage" | "history";

const SECTION_PATHS: Record<MembershipSectionKey, string> = {
  overview: "account/membership",
  benefits: "account/membership/benefits",
  usage: "account/membership/usage",
  manage: "account/membership/manage",
  history: "account/membership/history"
};

export function useMembershipShell(current: MembershipSectionKey) {
  const { t } = useI18n();
  const { localePath, locale } = useLocalePath();

  const sections = computed<VTabItem[]>(() =>
    (Object.keys(SECTION_PATHS) as MembershipSectionKey[]).map((key) => ({
      key,
      label: t(`membership.sections.${key}`),
      to: localePath(SECTION_PATHS[key])
    }))
  );

  const breadcrumbs = computed<VBreadcrumbItem[]>(() => [
    { label: t("ia.groups.billing"), to: localePath("account/orders") },
    { label: t("membership.accountTitle"), to: localePath("account/membership") },
    { label: t(`membership.sections.${current}`) }
  ]);

  return { sections, breadcrumbs, localePath, locale, t };
}

export function useMembershipState() {
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

/** Consumed + reserved against allocation, clamped for display. */
export function quotaPercent(row: MembershipSummary["quotas"][number]) {
  if (row.allocated_quantity <= 0) return 0;
  return Math.min(
    100,
    Math.round(((row.consumed_quantity + row.reserved_quantity) / row.allocated_quantity) * 100)
  );
}
