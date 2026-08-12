import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { VBreadcrumbItem, VTabItem } from "@vav/ui-core";

import { useLocalePath } from "@/composables/useAppNavigation";

export function useInteractionShell(current: string) {
  const { t } = useI18n();
  const { localePath } = useLocalePath();

  const sections = computed<VTabItem[]>(() => [
    { key: "matches", label: t("mm.sections.matches"), to: localePath("account/matchmaking/matches") },
    { key: "invitations", label: t("mm.sections.invitations"), to: localePath("account/matchmaking/invitations") },
    { key: "likes", label: t("mm.sections.likes"), to: localePath("account/matchmaking/likes") },
    { key: "skips", label: t("mm.sections.skips"), to: localePath("account/matchmaking/skips") }
  ]);

  const breadcrumbs = computed<VBreadcrumbItem[]>(() => [
    { label: t("ia.groups.matchmaking"), to: localePath("recommendations") },
    { label: t(`mm.sections.${current}`) }
  ]);

  return { sections, breadcrumbs, localePath, t };
}

/** Shared busy/error/notice state so every interaction page behaves the same. */
export function useInteractionState() {
  const busy = ref(false);
  const error = ref("");
  const notice = ref("");

  async function run(action: () => Promise<unknown>, successMessage: string, reload?: () => Promise<unknown>) {
    busy.value = true;
    error.value = "";
    try {
      await action();
      if (reload) await reload();
      notice.value = successMessage;
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "";
    } finally {
      busy.value = false;
    }
  }

  return { busy, error, notice, run };
}
