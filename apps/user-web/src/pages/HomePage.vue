<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { useSeo } from "@/composables/useSeo";
import { getPage } from "@/features/public-site/api/content";
import ContentRenderer from "@/features/public-site/components/ContentRenderer.vue";
import type { PublicContent } from "@/features/public-site/types";

const route = useRoute();
const { t } = useI18n();
const locale = computed(() => String(route.params.locale));
const seo = computed(() => ({
  title: t("brand.promise"),
  description: t("home.intro")
}));
useSeo(seo);

const services = [
  { key: "match", path: "membership", icon: "heart" },
  { key: "activities", path: "activities", icon: "spark" },
  { key: "courses", path: "courses", icon: "orbit" },
  { key: "guidance", path: "ai-assistant", icon: "voice" }
] as const;
const steps = ["discover", "grow", "connect"] as const;
const cmsHome = ref<PublicContent | null>(null);

onMounted(async () => {
  try {
    cmsHome.value = await getPage("home", locale.value);
  } catch {
    cmsHome.value = null;
  }
});
</script>

<template>
  <div class="home-experience">
    <section
      class="home-hero"
      aria-labelledby="home-hero-title"
    >
      <div
        class="home-hero-image"
        aria-hidden="true"
      />
      <div class="home-hero-copy">
        <p class="eyebrow">
          {{ t("home.eyebrow") }}
        </p>
        <h1 id="home-hero-title">
          {{ t("home.title") }}
        </h1>
        <p class="hero-intro">
          {{ t("home.intro") }}
        </p>
        <div class="hero-actions">
          <RouterLink
            class="primary-button hero-primary"
            :to="`/${locale}/auth/register`"
          >
            {{ t("home.start") }}
          </RouterLink>
          <RouterLink
            class="round-arrow"
            :to="`/${locale}/activities`"
            :aria-label="t('home.explore')"
          >
            <span aria-hidden="true">→</span>
          </RouterLink>
        </div>
      </div>

      <div class="member-proof">
        <div
          class="member-faces"
          aria-hidden="true"
        >
          <span>安</span><span>诚</span><span>真</span><span>爱</span>
        </div>
        <p><strong>25K+</strong> {{ t("home.members") }}</p>
      </div>

      <aside class="needs-panel">
        <p>{{ t("home.needsTitle") }}</p>
        <div class="needs-grid">
          <RouterLink
            v-for="service in services"
            :key="service.key"
            :to="`/${locale}/${service.path}`"
          >
            <span
              :class="['need-icon', `need-icon-${service.icon}`]"
              aria-hidden="true"
            />
            <strong>{{ t(`home.services.${service.key}`) }}</strong>
          </RouterLink>
        </div>
      </aside>

      <RouterLink
        class="ai-prompt-card"
        :to="`/${locale}/ai-assistant`"
      >
        <span
          class="ai-orb"
          aria-hidden="true"
        >
          VAV
        </span>
        <span class="ai-prompt-copy">
          <strong>{{ t("home.aiTitle") }}</strong>
          <small>{{ t("home.aiBody") }}</small>
          <span class="ai-prompt-field">
            {{ t("home.aiPlaceholder") }}
            <b aria-hidden="true">↑</b>
          </span>
        </span>
      </RouterLink>
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

    <section
      v-if="cmsHome"
      class="home-cms-content cms-page"
      :aria-label="cmsHome.title"
    >
      <ContentRenderer :blocks="cmsHome.content_blocks" />
    </section>
  </div>
</template>
