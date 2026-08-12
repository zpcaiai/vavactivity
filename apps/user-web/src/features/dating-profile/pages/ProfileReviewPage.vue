<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VButton, VCard, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import ProfileProgress from "@/features/dating-profile/components/ProfileProgress.vue";
import { useDatingProfile } from "@/features/dating-profile/composables/useDatingProfile";

const {
  profile,
  completeness,
  feedback,
  busy,
  error,
  notice,
  exists,
  completionPercent,
  missingRequired,
  canSubmit,
  steps,
  breadcrumbs,
  localePath,
  t,
  ensureLoaded,
  submitForReview,
  setLifecycle
} = useDatingProfile();

const changeSummary = ref("");

onMounted(async () => {
  await ensureLoaded();
  if (!changeSummary.value) changeSummary.value = t("dating.reviewPage.defaultSummary");
});
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('dating.steps.review')"
    :description="t('dating.reviewPage.description')"
    :breadcrumbs="breadcrumbs('review')"
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

    <template v-else>
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

      <VAlert
        v-if="missingRequired.length"
        tone="warning"
        :title="t('dating.reviewPage.blockedTitle')"
      >
        {{ missingRequired.join("、") }}
        <RouterLink :to="localePath('account/dating-profile/edit')">
          {{ t("dating.continueEditing") }}
        </RouterLink>
      </VAlert>

      <VCard
        v-if="feedback?.has_feedback"
        tone="warning"
      >
        <template #title>
          <h2>{{ t("dating.reviewPage.feedbackTitle") }}</h2>
        </template>
        <p>{{ feedback.message }}</p>
        <ul class="feedback-list">
          <li
            v-for="(item, index) in feedback.items"
            :key="index"
          >
            {{ item.field_code ?? t("dating.reviewPage.photoItem") }} · {{ item.decision }}
            <span v-if="item.user_message_safe">— {{ item.user_message_safe }}</span>
          </li>
        </ul>
      </VCard>

      <VCard>
        <template #title>
          <h2>{{ t("dating.reviewPage.submitTitle") }}</h2>
        </template>
        <template #description>
          {{ t("dating.reviewPage.submitDescription") }}
        </template>
        <label class="review-field">
          <span>{{ t("dating.reviewPage.changeSummary") }}</span>
          <textarea
            v-model="changeSummary"
            rows="3"
            maxlength="500"
          />
        </label>
        <template #footer>
          <VButton
            :disabled="!canSubmit"
            :loading="busy"
            @click="submitForReview(changeSummary)"
          >
            {{ t("dating.reviewPage.submit") }}
          </VButton>
          <small>{{ t("dating.reviewPage.immutable") }}</small>
        </template>
      </VCard>

      <VCard tone="soft">
        <template #title>
          <h2>{{ t("dating.reviewPage.lifecycleTitle") }}</h2>
        </template>
        <template #description>
          {{ t("dating.reviewPage.lifecycleDescription") }}
        </template>
        <template #footer>
          <VButton
            variant="secondary"
            @click="setLifecycle('pause')"
          >
            {{ t("dating.reviewPage.pause") }}
          </VButton>
          <VButton
            variant="secondary"
            @click="setLifecycle('reactivate')"
          >
            {{ t("dating.reviewPage.reactivate") }}
          </VButton>
        </template>
      </VCard>
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { color: var(--vav-color-text-muted); margin: 0; }
small { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); }
.feedback-list { display: grid; gap: var(--vav-space-1); margin: 0; padding-inline-start: var(--vav-space-5); }
.review-field { display: grid; gap: var(--vav-space-1); }
.review-field span { font-size: var(--vav-font-size-sm); font-weight: var(--vav-font-weight-semibold); }

.review-field textarea {
  background: var(--vav-color-surface-raised);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-input-radius);
  color: var(--vav-color-text);
  font: inherit;
  padding: var(--vav-space-2) var(--vav-component-input-padding-inline);
}
</style>
