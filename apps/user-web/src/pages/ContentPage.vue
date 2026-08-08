<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { useSeo } from "@/composables/useSeo";

const route = useRoute();
const { t } = useI18n();
const key = computed(() => String(route.meta.copyKey));
const title = computed(() => t(`pages.${key.value}.title`));
const body = computed(() => t(`pages.${key.value}.body`));

useSeo(computed(() => ({ title: title.value, description: body.value })));
</script>

<template>
  <section class="editorial-page">
    <div class="editorial-copy">
      <p class="eyebrow">
        {{ t(`pages.${key}.eyebrow`) }}
      </p>
      <h1>{{ title }}</h1>
      <p>{{ body }}</p>
      <div class="availability-card">
        <span class="status-dot" />
        <div>
          <strong>{{ t("common.coming") }}</strong>
          <p>Batch 1 establishes the verified entry point and contract boundary.</p>
        </div>
      </div>
    </div>
    <div
      class="editorial-art"
      aria-hidden="true"
    >
      <span class="art-ring" />
      <span class="art-line" />
      <strong>VAV</strong>
    </div>
  </section>
</template>
