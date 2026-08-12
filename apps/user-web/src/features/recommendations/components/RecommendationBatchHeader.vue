<script setup lang="ts">
import { computed } from "vue";

import {
  batchStatusText,
  batchTypeText
} from "@/features/recommendations/composables/useRecommendationBatch";
import type { RecommendationBatch } from "@/features/recommendations/types";

const props = defineProps<{
  batch: RecommendationBatch | null;
  itemCount: number;
  paused: boolean;
  requesting?: boolean;
}>();

const emit = defineEmits<{ (event: "request-batch"): void }>();

const expiresText = computed(() => {
  if (!props.batch?.expires_at) return "";
  const moment = new Date(props.batch.expires_at);
  if (Number.isNaN(moment.getTime())) return "";
  return moment.toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" });
});
</script>

<template>
  <header class="batch-header">
    <div
      v-if="batch"
      class="status-bar"
    >
      <span class="chip">第 {{ batch.batch_number }} 批</span>
      <span class="chip">{{ batchTypeText(batch.batch_type) }}</span>
      <span class="chip">{{ batchStatusText(batch.status) }}</span>
      <span class="chip">本批 {{ itemCount }} / {{ batch.generated_size }} 位</span>
      <span
        v-if="expiresText"
        class="chip"
      >有效期至 {{ expiresText }}</span>
    </div>
    <p
      v-else
      class="hint"
    >
      今天还没有生成推荐批次。
    </p>

    <p
      v-if="paused"
      class="hint paused"
    >
      你已暂停接收推荐，恢复后才会生成新的批次。
    </p>

    <button
      type="button"
      class="primary"
      :disabled="paused || requesting"
      @click="emit('request-batch')"
    >
      {{ requesting ? "正在获取…" : "获取今日推荐" }}
    </button>
    <p class="hint">
      重复获取只会返回同一批推荐，不会超出你设置的每日数量上限。
    </p>
  </header>
</template>

<style scoped>
.batch-header { display: flex; flex-direction: column; gap: 0.6rem; }
.status-bar { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.chip { padding: 0.15rem 0.6rem; border-radius: 999px; background: rgba(0, 0, 0, 0.06); font-size: 0.8rem; }
.hint { font-size: 0.85rem; opacity: 0.75; margin: 0; }
.hint.paused { color: var(--vav-color-danger); opacity: 1; }
button.primary { align-self: flex-start; padding: 0.6rem 1.4rem; border-radius: 0.5rem; border: none; background: var(--vav-color-text); color: var(--vav-color-surface-raised); cursor: pointer; }
button.primary:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
