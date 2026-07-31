<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

const props = defineProps<{ mode: "login" | "register" }>();
const route = useRoute();
const { t } = useI18n();
const locale = computed(() => String(route.params.locale));
const title = computed(() =>
  props.mode === "login" ? t("auth.loginTitle") : t("auth.registerTitle")
);
</script>

<template>
  <section class="auth-page">
    <div class="auth-card">
      <span
        class="brand-mark"
        aria-hidden="true"
      >V</span>
      <p class="eyebrow">
        VAV ACCOUNT
      </p>
      <h1>{{ title }}</h1>
      <p>{{ t("auth.unavailable") }}</p>
      <RouterLink
        class="primary-button"
        :to="`/${locale}/`"
      >
        {{ t("auth.returnHome") }}
      </RouterLink>
    </div>
  </section>
</template>

