<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { VAlert, VCard } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { useLocalePath } from "@/composables/useAppNavigation";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const { localePath } = useLocalePath();
const auth = useAuthStore();
</script>

<template>
  <UserPageLayout
    width="reading"
    :eyebrow="t('safety.eyebrow')"
    :title="t('safety.supportTitle')"
    :description="t('safety.emergency')"
  >
    <VAlert
      tone="warning"
      :title="t('safety.noContactTitle')"
    >
      {{ t("safety.noContact") }}
    </VAlert>

    <VCard>
      <template #title>
        <h2>{{ t("safety.whatYouCanDoTitle") }}</h2>
      </template>
      <ul class="support-list">
        <li>{{ t("safety.canBlock") }}</li>
        <li>{{ t("safety.canRevoke") }}</li>
        <li>{{ t("safety.canReport") }}</li>
      </ul>
      <template #footer>
        <RouterLink
          class="support-cta"
          :to="auth.user ? localePath('account/safety') : localePath('auth/login')"
        >
          {{ auth.user ? t("safety.openCenter") : t("safety.signInFirst") }}
        </RouterLink>
        <RouterLink :to="localePath('contact')">
          {{ t("help.contactSupport") }}
        </RouterLink>
      </template>
    </VCard>

    <VCard tone="soft">
      <template #title>
        <h2>{{ t("safety.privacyTitle") }}</h2>
      </template>
      <p>{{ t("safety.privacyBoundary") }}</p>
    </VCard>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { margin: 0; color: var(--vav-color-text-muted); }
.support-list { display: grid; gap: var(--vav-space-2); margin: 0; padding-inline-start: var(--vav-space-5); }

.support-cta {
  align-items: center;
  background: var(--vav-color-danger);
  border-radius: var(--vav-radius-pill);
  color: var(--vav-color-on-action);
  display: inline-flex;
  font-weight: var(--vav-font-weight-semibold);
  min-block-size: var(--vav-component-button-height);
  padding-inline: var(--vav-space-4);
  text-decoration: none;
}
</style>
