<script setup lang="ts">
import { onMounted } from "vue";
import { VAlert, VButton, VCard, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import ProfileProgress from "@/features/dating-profile/components/ProfileProgress.vue";
import { useDatingProfile } from "@/features/dating-profile/composables/useDatingProfile";

const {
  profile,
  completeness,
  busy,
  error,
  notice,
  exists,
  completionPercent,
  missingRequired,
  steps,
  breadcrumbs,
  localePath,
  t,
  ensureLoaded,
  createProfile
} = useDatingProfile();

onMounted(() => void ensureLoaded());
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('dating.title')"
    :description="t('dating.description')"
    :breadcrumbs="breadcrumbs('overview')"
    :sections="exists ? steps : undefined"
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
      v-if="busy && !profile"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <VPageState
      v-else-if="profile && !exists"
      state="empty"
      :title="t('dating.emptyTitle')"
      :message="t('dating.emptyMessage')"
    >
      <VButton
        :loading="busy"
        @click="createProfile"
      >
        {{ t("dating.create") }}
      </VButton>
    </VPageState>

    <template v-else-if="exists">
      <ProfileProgress
        :profile="profile"
        :completeness="completeness"
        :percent="completionPercent"
        :missing-count="missingRequired.length"
        :measure-note="t('dating.measureNote')"
        :missing-label="t('dating.missingRequired')"
        :number-label="t('dating.number')"
        :status-label="t('dating.status')"
        :review-label="t('dating.review')"
        :approved-label="t('dating.approvedVersion')"
        :progress-label="t('dating.completeness')"
      />

      <VCard>
        <template #title>
          <h2>{{ t("dating.nextStepTitle") }}</h2>
        </template>
        <template #description>
          {{ t("dating.nextStepDescription") }}
        </template>
        <ul
          v-if="missingRequired.length"
          class="overview-missing"
        >
          <li
            v-for="field in missingRequired.slice(0, 8)"
            :key="field"
          >
            {{ field }}
          </li>
        </ul>
        <p v-else>
          {{ t("dating.allRequiredDone") }}
        </p>
        <template #footer>
          <RouterLink
            class="overview-cta"
            :to="localePath('account/dating-profile/edit')"
          >
            {{ t("dating.continueEditing") }}
          </RouterLink>
          <RouterLink :to="localePath('account/dating-profile/review')">
            {{ t("dating.steps.review") }}
          </RouterLink>
        </template>
      </VCard>

      <VAlert
        tone="info"
        :title="t('dating.privacyDefaultTitle')"
      >
        {{ t("dating.privacyDefault") }}
      </VAlert>
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { color: var(--vav-color-text-muted); margin: 0; }
.overview-missing { color: var(--vav-color-danger); display: grid; gap: var(--vav-space-1); margin: 0; padding-inline-start: var(--vav-space-5); }

.overview-cta {
  align-items: center;
  background: var(--vav-color-action-primary);
  border-radius: var(--vav-radius-pill);
  color: var(--vav-color-on-action);
  display: inline-flex;
  font-weight: var(--vav-font-weight-semibold);
  min-block-size: var(--vav-component-button-height);
  padding-inline: var(--vav-space-4);
  text-decoration: none;
}
</style>
