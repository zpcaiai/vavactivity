<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { recommendationsApi } from "@/features/recommendations/api";
import FeedbackReasonDialog from "@/features/recommendations/components/FeedbackReasonDialog.vue";
import RecommendationBatchHeader from "@/features/recommendations/components/RecommendationBatchHeader.vue";
import RecommendationEmptyState from "@/features/recommendations/components/RecommendationEmptyState.vue";
import RecommendationList from "@/features/recommendations/components/RecommendationList.vue";
import { useRecommendationBatch } from "@/features/recommendations/composables/useRecommendationBatch";
import { useRecommendationFeedback } from "@/features/recommendations/composables/useRecommendationFeedback";
import {
  ineligibleReasonText,
  useRecommendations
} from "@/features/recommendations/composables/useRecommendations";

const route = useRoute();
const router = useRouter();

const {
  items,
  batch,
  emptyState,
  eligible,
  paused,
  ineligibleReasons,
  loading,
  error,
  load
} = useRecommendations();
const { requesting, error: batchError, notice: batchNotice, requestBatch } = useRecommendationBatch();
const {
  dialogOpen,
  activeItemId,
  submitting: feedbackSubmitting,
  error: feedbackError,
  notice: feedbackNotice,
  openDialog,
  closeDialog,
  submitNotRelevant: sendNotRelevant
} = useRecommendationFeedback();

const reasonCodes = ref<string[]>([]);
const pausing = ref(false);

const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const basePath = computed(() => `/${locale.value}/recommendations`);
const preferencesPath = computed(() => `/${locale.value}/account/recommendation-preferences`);
const historyPath = computed(() => `/${locale.value}/account/recommendation-history`);
const transparencyPath = computed(() => `/${locale.value}/account/recommendation-transparency`);
const datingPreferencesPath = computed(
  () => `/${locale.value}/account/dating-profile/preferences`
);
const activitiesPath = computed(() => `/${locale.value}/activities`);

async function loadReasonCodes() {
  try {
    const preferences = await recommendationsApi.preferences();
    reasonCodes.value = preferences.feedback_reason_codes;
  } catch {
    // The dialog falls back to the built-in reason list.
    reasonCodes.value = [];
  }
}

async function refresh() {
  await load();
}

async function onRequestBatch() {
  const result = await requestBatch("daily");
  if (result) await load();
}

async function openItem(itemId: string) {
  await router.push(`${basePath.value}/${itemId}`);
}

async function submitNotRelevant(payload: { reasonCode: string; reasonDetails: string }) {
  const itemId = activeItemId.value;
  if (!itemId) return;
  const ok = await sendNotRelevant(itemId, payload.reasonCode, payload.reasonDetails);
  if (ok) await load();
}

async function pauseRecommendations() {
  pausing.value = true;
  try {
    await recommendationsApi.savePreferences({ recommendations_paused: true });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "暂停推荐失败";
  } finally {
    pausing.value = false;
  }
}

onMounted(async () => {
  await load();
  await loadReasonCodes();
});
</script>

<template>
  <section class="recommendations">
    <p class="eyebrow">
      BATCH 14 · RECOMMENDATIONS
    </p>
    <h1>今日推荐</h1>
    <p class="intro">
      推荐只根据你自己填写的择偶条件和双方公开的档案资料生成。平台不提供匹配分数或百分比，
      也不会显示对方对你的看法。是否继续了解，完全由你决定。
    </p>

    <nav class="links">
      <RouterLink :to="preferencesPath">
        推荐设置
      </RouterLink>
      <RouterLink :to="historyPath">
        推荐记录
      </RouterLink>
      <RouterLink :to="transparencyPath">
        推荐说明
      </RouterLink>
    </nav>

    <p
      v-if="error || batchError || feedbackError"
      class="alert error"
      role="alert"
    >
      {{ error || batchError || feedbackError }}
    </p>
    <p
      v-if="batchNotice || feedbackNotice"
      class="alert notice"
      role="status"
    >
      {{ batchNotice || feedbackNotice }}
    </p>

    <div
      v-if="!eligible && ineligibleReasons.length"
      class="panel"
    >
      <h2>暂时无法生成推荐</h2>
      <ul class="plain">
        <li
          v-for="reason in ineligibleReasons"
          :key="reason"
        >
          {{ ineligibleReasonText(reason) }}
        </li>
      </ul>
      <RouterLink :to="`/${locale}/account/dating-profile`">
        前往婚恋档案
      </RouterLink>
    </div>

    <RecommendationBatchHeader
      :batch="batch"
      :item-count="items.length"
      :paused="paused"
      :requesting="requesting"
      @request-batch="onRequestBatch"
    />

    <p v-if="loading">
      正在加载推荐…
    </p>

    <RecommendationList
      v-else-if="items.length"
      :items="items"
      :base-path="basePath"
      :preferences-path="preferencesPath"
      @open="openItem"
      @not-relevant="openDialog"
      @interacted="refresh"
    />

    <RecommendationEmptyState
      v-else
      :empty-state="emptyState"
      :preferences-path="preferencesPath"
      :dating-preferences-path="datingPreferencesPath"
      :activities-path="activitiesPath"
      @pause="pauseRecommendations"
    />

    <p
      v-if="pausing"
      class="hint"
    >
      正在暂停推荐…
    </p>

    <button
      type="button"
      class="quiet"
      @click="refresh"
    >
      重新加载
    </button>

    <FeedbackReasonDialog
      :open="dialogOpen"
      :reason-codes="reasonCodes"
      :submitting="feedbackSubmitting"
      :error="feedbackError"
      @submit="submitNotRelevant"
      @close="closeDialog"
    />
  </section>
</template>

<style scoped>
.recommendations { display: flex; flex-direction: column; gap: 1.25rem; padding: 2rem 0; }
.eyebrow { letter-spacing: 0.18em; font-size: 0.75rem; opacity: 0.7; }
.intro { max-width: 62ch; line-height: 1.7; }
.links { display: flex; flex-wrap: wrap; gap: 1rem; font-size: 0.9rem; }
.alert { padding: 0.75rem 1rem; border-radius: 0.5rem; margin: 0; }
.alert.error { background: #fdecea; color: #8a1c12; }
.alert.notice { background: #eaf6ec; color: #1c5a2a; }
.panel { display: flex; flex-direction: column; gap: 0.6rem; padding: 1.25rem; border: 1px solid rgba(0, 0, 0, 0.1); border-radius: 0.75rem; }
.panel h2 { margin: 0; font-size: 1rem; }
.plain { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.9rem; }
.hint { font-size: 0.85rem; opacity: 0.75; margin: 0; }
button.quiet { align-self: flex-start; padding: 0.4rem 1rem; border-radius: 0.5rem; border: 1px dashed rgba(0, 0, 0, 0.25); background: transparent; cursor: pointer; }
</style>
