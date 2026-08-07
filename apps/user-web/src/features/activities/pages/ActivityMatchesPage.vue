<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { activityApi, type ActivityMatch } from "../api";

const items = ref<ActivityMatch[]>([]);
const { t } = useI18n();
const error = ref("");

onMounted(async () => {
  try {
    items.value = (await activityApi.matches()).items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "互选结果加载失败";
  }
});
</script>

<template>
  <section class="commerce-page">
    <p class="eyebrow">
      PRIVATE MUTUAL CHOICES
    </p>
    <h1>{{ t("activities.privateMatches") }}</h1>
    <p>{{ t("activities.oneSidedPrivate") }}</p>
    <p
      v-if="error"
      class="form-error"
    >
      {{ error }}
    </p>
    <p v-if="!error && !items.length">
      {{ t("activities.noMatches") }}
    </p>
    <article
      v-for="item in items"
      :key="item.id"
      class="commerce-card"
    >
      <strong>{{ new Date(item.matched_at).toLocaleString() }}</strong>
      <span>{{ item.status }}</span>
      <small>{{ t("activities.contactPrivate") }}</small>
    </article>
  </section>
</template>
