<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { recommendationsApi } from "@/features/recommendations/api";
import FeedbackReasonDialog from "@/features/recommendations/components/FeedbackReasonDialog.vue";
import RecommendationCard from "@/features/recommendations/components/RecommendationCard.vue";
import { useRecommendationExposure } from "@/features/recommendations/composables/useRecommendationExposure";
import { useRecommendationFeedback } from "@/features/recommendations/composables/useRecommendationFeedback";
import type { RecommendationItem } from "@/features/recommendations/types";

const route = useRoute();
const item = ref<RecommendationItem>();
const loading = ref(false);
const error = ref("");
const reasonCodes = ref<string[]>([]);

const {
  dialogOpen,
  submitting: feedbackSubmitting,
  error: feedbackError,
  notice: feedbackNotice,
  openDialog,
  closeDialog,
  submitNotRelevant: sendNotRelevant
} = useRecommendationFeedback();

const { reportProfileOpened } = useRecommendationExposure({ source: "recommendation_detail" });

const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const itemId = computed(() => String(route.params.recommendationItemId ?? ""));
const listPath = computed(() => `/${locale.value}/recommendations`);
const preferencesPath = computed(() => `/${locale.value}/account/recommendation-preferences`);
const transparencyPath = computed(() => `/${locale.value}/account/recommendation-transparency`);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    item.value = await recommendationsApi.get(itemId.value);
    reportProfileOpened(itemId.value, "recommendation_detail");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "推荐详情加载失败";
  } finally {
    loading.value = false;
  }
}

async function loadReasonCodes() {
  try {
    reasonCodes.value = (await recommendationsApi.preferences()).feedback_reason_codes;
  } catch {
    reasonCodes.value = [];
  }
}

async function submitNotRelevant(payload: { reasonCode: string; reasonDetails: string }) {
  const ok = await sendNotRelevant(itemId.value, payload.reasonCode, payload.reasonDetails);
  if (ok) await load();
}

onMounted(async () => {
  await load();
  await loadReasonCodes();
});
</script>

<template>
  <section class="recommendation-detail">
    <RouterLink :to="listPath">
      ← 返回今日推荐
    </RouterLink>
    <h1>推荐详情</h1>

    <p
      v-if="error || feedbackError"
      class="alert error"
      role="alert"
    >
      {{ error || feedbackError }}
    </p>
    <p
      v-if="feedbackNotice"
      class="alert notice"
      role="status"
    >
      {{ feedbackNotice }}
    </p>

    <p v-if="loading">
      正在加载推荐详情…
    </p>

    <RecommendationCard
      v-else-if="item"
      :item="item"
      detailed
      :preferences-path="preferencesPath"
      @not-relevant="openDialog"
    />

    <p
      v-else-if="!error"
      class="hint"
    >
      这条推荐已不可查看，可能已过期或不再符合展示条件。
    </p>

    <p class="hint">
      联系方式、精确出生日期和对方的择偶条件不会在此展示。感兴趣与暂时跳过不会向对方公开；只有双方都感兴趣时才会建立互选。
    </p>
    <RouterLink :to="transparencyPath">
      了解推荐依据
    </RouterLink>

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
.recommendation-detail { display: flex; flex-direction: column; gap: 1rem; padding: 2rem 0; }
.recommendation-detail h1 { margin: 0; font-size: 1.4rem; }
.alert { padding: 0.75rem 1rem; border-radius: 0.5rem; margin: 0; }
.alert.error { background: var(--vav-color-surface-danger); color: var(--vav-color-danger); }
.alert.notice { background: var(--vav-color-surface-success); color: var(--vav-color-success); }
.hint { font-size: 0.85rem; opacity: 0.75; line-height: 1.6; margin: 0; max-width: 62ch; }
</style>
