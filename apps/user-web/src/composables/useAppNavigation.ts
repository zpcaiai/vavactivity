import { computed, type ComputedRef } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import type { AppNavGroup, AppTabItem } from "@vav/ui-user";

import {
  appIa,
  isGroupVisible,
  isItemVisible,
  mobileTabs,
  publicIa,
  type IaContext
} from "@/navigation/ia";
import { useAuthStore } from "@/stores/auth";

export function useLocalePath() {
  const route = useRoute();
  const locale = computed(() => String(route.params.locale ?? "zh-CN"));
  const localePath = (path: string) => `/${locale.value}${path ? `/${path}` : "/"}`;
  return { locale, localePath };
}

export function useAppNavigation(badges?: ComputedRef<Record<string, number>>) {
  const { t } = useI18n();
  const route = useRoute();
  const auth = useAuthStore();
  const { locale, localePath } = useLocalePath();

  const context = computed<IaContext>(() => ({
    relationshipStatus: (auth.user as { relationship_status?: string } | null)?.relationship_status,
    emailVerified: Boolean(auth.user?.email_verified)
  }));

  const groups = computed<AppNavGroup[]>(() =>
    appIa
      .filter((group) => isGroupVisible(group, context.value))
      .map((group) => ({
        key: group.key,
        label: t(group.labelKey),
        glyph: group.glyph,
        to: localePath(group.path),
        items: group.items
          .filter((item) => isItemVisible(item, context.value))
          .map((item) => ({
            key: item.key,
            label: t(item.labelKey),
            to: localePath(item.path),
            exact: item.exact,
            critical: item.critical,
            badge: badges?.value[item.key]
          }))
      }))
  );

  const tabs = computed<AppTabItem[]>(() =>
    mobileTabs
      .filter((tab) => !tab.singlesOnly || isGroupVisible({ ...tab, items: [], labelKey: tab.labelKey }, context.value))
      .map((tab) => ({
        key: tab.key,
        label: t(tab.labelKey),
        glyph: tab.glyph,
        to: localePath(tab.path),
        badge: badges?.value[tab.key]
      }))
  );

  const publicLinks = computed(() =>
    publicIa.map((item) => ({ key: item.key, label: t(item.labelKey), to: localePath(item.path) }))
  );

  const activePath = computed(() => route.path);

  return { groups, tabs, publicLinks, activePath, locale, localePath, context };
}
