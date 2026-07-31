<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

const route = useRoute();
const { t } = useI18n();
const menuOpen = ref(false);
const locale = computed(() => String(route.params.locale));

const links = [
  { key: "about", path: "about" },
  { key: "articles", path: "articles" },
  { key: "activities", path: "activities" },
  { key: "courses", path: "courses" },
  { key: "counseling", path: "counseling" },
  { key: "ai", path: "ai-assistant" }
] as const;
</script>

<template>
  <div class="site-shell">
    <header class="site-header">
      <RouterLink
        class="brand"
        :to="`/${locale}/`"
        aria-label="VAV home"
      >
        <span
          class="brand-mark"
          aria-hidden="true"
        >V</span>
        <span>
          <strong>VAV</strong>
          <small>{{ t("brand.promise") }}</small>
        </span>
      </RouterLink>

      <button
        class="menu-button"
        type="button"
        :aria-label="t('nav.menu')"
        :aria-expanded="menuOpen"
        @click="menuOpen = !menuOpen"
      >
        <span />
        <span />
      </button>

      <nav
        :class="['main-nav', { open: menuOpen }]"
        aria-label="Primary"
      >
        <RouterLink
          v-for="link in links"
          :key="link.key"
          :to="`/${locale}/${link.path}`"
          @click="menuOpen = false"
        >
          {{ t(`nav.${link.key}`) }}
        </RouterLink>
        <RouterLink
          class="account-link"
          :to="`/${locale}/account`"
          @click="menuOpen = false"
        >
          {{ t("nav.account") }}
        </RouterLink>
        <RouterLink
          class="language-link"
          to="/"
          @click="menuOpen = false"
        >
          {{ t("common.language") }}
        </RouterLink>
      </nav>
    </header>

    <main id="main-content">
      <RouterView />
    </main>

    <footer class="site-footer">
      <div>
        <span
          class="brand-mark small"
          aria-hidden="true"
        >V</span>
        <strong>VAV</strong>
      </div>
      <p>{{ t("brand.promise") }} · © 2026</p>
      <RouterLink :to="`/${locale}/about`">
        {{ t("nav.about") }}
      </RouterLink>
    </footer>
  </div>
</template>

