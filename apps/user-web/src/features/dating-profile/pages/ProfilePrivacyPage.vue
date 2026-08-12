<script setup lang="ts">
import { onMounted } from "vue";
import { VAlert, VButton, VCard, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import {
  useDatingProfile,
  VISIBILITY_OPTIONS
} from "@/features/dating-profile/composables/useDatingProfile";

const {
  privacy,
  busy,
  error,
  notice,
  exists,
  steps,
  breadcrumbs,
  localePath,
  t,
  ensureLoaded,
  savePrivacy
} = useDatingProfile();

onMounted(() => void ensureLoaded());
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('dating.steps.privacy')"
    :description="t('dating.privacyPage.description')"
    :breadcrumbs="breadcrumbs('privacy')"
    :sections="steps"
    :sections-label="t('dating.stepsLabel')"
  >
    <VAlert
      v-if="error"
      tone="danger"
      :title="t('common.loadFailed')"
    >
      {{ error }}
    </VAlert>
    <VAlert
      v-if="notice"
      tone="success"
      :title="t('common.done')"
      live
    >
      {{ notice }}
    </VAlert>

    <VPageState
      v-if="!exists && !busy"
      state="empty"
      :title="t('dating.emptyTitle')"
      :message="t('dating.emptyMessage')"
    >
      <RouterLink :to="localePath('account/dating-profile')">
        {{ t("dating.goToOverview") }}
      </RouterLink>
    </VPageState>

    <template v-else-if="privacy">
      <VAlert
        tone="info"
        :title="t('dating.privacyPage.boundaryTitle')"
      >
        {{ t("dating.privacyPage.boundary") }}
      </VAlert>

      <VCard>
        <template #title>
          <h2>{{ t("dating.privacyPage.poolTitle") }}</h2>
        </template>
        <label class="privacy-toggle">
          <input
            v-model="privacy.visible_in_matchmaking"
            type="checkbox"
          >
          <span>{{ t("dating.privacyPage.inPool") }}</span>
        </label>
      </VCard>

      <VCard>
        <template #title>
          <h2>{{ t("dating.privacyPage.fieldsTitle") }}</h2>
        </template>
        <template #description>
          {{ t("dating.privacyPage.fieldsDescription") }}
        </template>
        <div class="visibility-grid">
          <label
            v-for="(value, field) in privacy.field_visibility"
            :key="field"
          >
            <span>{{ field }}</span>
            <select v-model="privacy.field_visibility[field]">
              <option
                v-for="option in VISIBILITY_OPTIONS"
                :key="option"
                :value="option"
              >
                {{ t(`dating.visibility.${option}`) }}
              </option>
            </select>
          </label>
        </div>
        <template #footer>
          <VButton
            :loading="busy"
            @click="savePrivacy"
          >
            {{ t("dating.privacyPage.save") }}
          </VButton>
        </template>
      </VCard>
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
.privacy-toggle { align-items: center; display: flex; gap: var(--vav-space-2); }
.visibility-grid { display: grid; gap: var(--vav-space-3); grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); }
.visibility-grid label { display: grid; gap: var(--vav-space-1); }
.visibility-grid span { font-size: var(--vav-font-size-sm); font-weight: var(--vav-font-weight-semibold); overflow-wrap: anywhere; }

.visibility-grid select {
  background: var(--vav-color-surface-raised);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-input-radius);
  color: var(--vav-color-text);
  font: inherit;
  min-block-size: var(--vav-component-input-height);
  padding-inline: var(--vav-component-input-padding-inline);
}
</style>
