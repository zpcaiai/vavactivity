<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "vue-i18n";

import { activityApi, type PublicActivity } from "../api";

const route = useRoute();

/**
 * `toLocaleString()` with no locale follows the *browser*, so a zh-CN page
 * printed "9/12/2026, 7:06:40 AM". Format against the route locale, and drop
 * the seconds — a start time does not need them.
 */
function formatStartsAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(String(route.params.locale ?? "zh-CN"), {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}
const { t } = useI18n();
const activities = ref<PublicActivity[]>([]);
const loading = ref(true);
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    activities.value = (await activityApi.list(String(route.params.locale))).items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("activities.loadError");
  } finally {
    loading.value = false;
  }
}

onMounted(() => void load());
watch(() => route.params.locale, () => void load());
</script>

<template>
  <section class="catalog-page activity-page">
    <header class="catalog-heading">
      <div>
        <p class="eyebrow">
          {{ t("activities.eyebrow") }}
        </p>
        <h1>{{ t("activities.title") }}</h1>
        <p>{{ t("activities.privacyBoundary") }}</p>
      </div>
    </header>
    <p
      v-if="loading"
      role="status"
    >
      {{ t("activities.loading") }}
    </p>
    <p
      v-else-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <div
      v-else
      class="product-grid"
    >
      <article
        v-for="activity in activities"
        :key="activity.id"
        class="product-card"
      >
        <p class="eyebrow">
          {{ activity.format }} · {{ activity.status }}
        </p>
        <h2>{{ activity.title }}</h2>
        <p>{{ activity.summary }}</p>
        <p>
          <strong>{{ formatStartsAt(activity.starts_at) }}</strong>
          · {{ activity.timezone }}
        </p>
        <RouterLink :to="`/${String(route.params.locale)}/activities/${activity.slug}`">
          {{ t("activities.view") }}
        </RouterLink>
      </article>
    </div>
  </section>
</template>
