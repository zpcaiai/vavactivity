<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { useSeo } from "@/composables/useSeo";

const route = useRoute();
const { t } = useI18n();
const locale = computed(() => String(route.params.locale));
const seo = computed(() => ({
  title: t("brand.promise"),
  description: t("home.intro")
}));
useSeo(seo);

const steps = ["discover", "grow", "connect"] as const;
</script>

<template>
  <div>
    <section class="hero">
      <div class="hero-copy">
        <p class="eyebrow">
          {{ t("home.eyebrow") }}
        </p>
        <h1>{{ t("home.title") }}</h1>
        <p class="hero-intro">
          {{ t("home.intro") }}
        </p>
        <div class="hero-actions">
          <RouterLink
            class="primary-button"
            :to="`/${locale}/activities`"
          >
            {{ t("home.explore") }}
          </RouterLink>
          <RouterLink
            class="text-link"
            :to="`/${locale}/about`"
          >
            {{ t("home.learn") }} <span aria-hidden="true">→</span>
          </RouterLink>
        </div>
      </div>
      <div
        class="hero-art"
        aria-hidden="true"
      >
        <div class="orbit orbit-one" />
        <div class="orbit orbit-two" />
        <div class="figures">
          <span />
          <span />
        </div>
        <p>V · A · V</p>
      </div>
    </section>

    <section
      class="journey-section"
      aria-labelledby="journey-title"
    >
      <div class="section-heading">
        <p class="eyebrow">
          VAV PATH
        </p>
        <h2 id="journey-title">
          {{ t("home.trustTitle") }}
        </h2>
        <p>{{ t("home.trustBody") }}</p>
      </div>
      <div class="journey-grid">
        <article
          v-for="(step, index) in steps"
          :key="step"
        >
          <span class="step-number">0{{ index + 1 }}</span>
          <h3>{{ t(`home.steps.${step}`) }}</h3>
          <p>{{ t(`home.steps.${step}Body`) }}</p>
        </article>
      </div>
    </section>

    <section class="foundation-note">
      <span class="status-dot" />
      <div>
        <strong>{{ t("common.coming") }}</strong>
        <p>Foundation release · Batch 1</p>
      </div>
    </section>
  </div>
</template>

