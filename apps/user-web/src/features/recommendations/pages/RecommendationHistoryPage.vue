<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { recommendationsApi } from "@/features/recommendations/api";
import {
  batchStatusText,
  batchTypeText
} from "@/features/recommendations/composables/useRecommendationBatch";
import type { HistoryBatch } from "@/features/recommendations/types";

const route = useRoute();
const batches = ref<HistoryBatch[]>([]);
const loading = ref(false);
const error = ref("");

const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const listPath = computed(() => `/${locale.value}/recommendations`);

function formatMoment(value: string | null) {
  if (!value) return "—";
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return "—";
  return moment.toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" });
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    batches.value = (await recommendationsApi.history()).batches;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "推荐记录加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="recommendation-history">
    <RouterLink :to="listPath">
      ← 返回今日推荐
    </RouterLink>
    <h1>推荐记录</h1>
    <p class="intro">
      这里只显示你收到过的推荐批次与数量，帮助你了解推荐的节奏。已过期批次中的具体档案不再展示。
    </p>

    <p
      v-if="error"
      class="alert error"
      role="alert"
    >
      {{ error }}
    </p>
    <p v-if="loading">
      正在加载推荐记录…
    </p>

    <table
      v-else-if="batches.length"
      class="history"
    >
      <caption class="sr-only">
        推荐批次记录
      </caption>
      <thead>
        <tr>
          <th scope="col">
            批次
          </th>
          <th scope="col">
            类型
          </th>
          <th scope="col">
            状态
          </th>
          <th scope="col">
            数量
          </th>
          <th scope="col">
            生成时间
          </th>
          <th scope="col">
            有效期至
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="batch in batches"
          :key="batch.batch_id"
        >
          <td>第 {{ batch.batch_number }} 批</td>
          <td>{{ batchTypeText(batch.batch_type) }}</td>
          <td>{{ batchStatusText(batch.status) }}</td>
          <td>{{ batch.generated_size }} 位</td>
          <td>{{ formatMoment(batch.created_at) }}</td>
          <td>{{ formatMoment(batch.expires_at) }}</td>
        </tr>
      </tbody>
    </table>

    <p
      v-else
      class="hint"
    >
      还没有推荐记录。生成第一批推荐后，这里会显示批次与数量。
    </p>
  </section>
</template>

<style scoped>
.recommendation-history { display: flex; flex-direction: column; gap: 1rem; padding: 2rem 0; }
.recommendation-history h1 { margin: 0; font-size: 1.4rem; }
.intro { max-width: 62ch; line-height: 1.7; margin: 0; }
.alert { padding: 0.75rem 1rem; border-radius: 0.5rem; margin: 0; }
.alert.error { background: #fdecea; color: #8a1c12; }
.history { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.history th, .history td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid rgba(0, 0, 0, 0.08); }
.hint { font-size: 0.85rem; opacity: 0.75; margin: 0; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
