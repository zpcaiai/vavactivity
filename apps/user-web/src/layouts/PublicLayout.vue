<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { VSkipLink } from "@vav/ui-core";

import {
  getNavigation,
  type PublicNavigationItem
} from "@/features/public-site/api/content";
import { useAuthStore } from "@/stores/auth";
import NotificationBell from "@/features/notifications/components/NotificationBell.vue";
import GlobalCommandPalette from "@/features/experience/components/GlobalCommandPalette.vue";

const route = useRoute();
const { t } = useI18n();
const auth = useAuthStore();
const menuOpen = ref(false);
const locale = computed(() => String(route.params.locale));
const configuredLinks = ref<PublicNavigationItem[]>([]);

const fallbackLinks = [
  { key: "home", path: "" },
  { key: "activities", path: "activities" },
  { key: "courses", path: "courses" },
  { key: "counseling", path: "counseling" },
  { key: "ai", path: "ai-assistant" }
] as const;

const routePaths: Record<string, string> = {
  home: "",
  about: "about",
  services: "services",
  contact: "contact",
  articles: "articles",
  stories: "stories",
  activities: "activities",
  courses: "courses",
  counseling: "counseling",
  ai: "ai-assistant"
};

const visibleConfiguredLinks = computed(() =>
  configuredLinks.value.filter((item) => !item.required_auth || Boolean(auth.user))
);

function internalPath(item: PublicNavigationItem) {
  if (item.link_type === "content") {
    return `/${locale.value}/${item.target_slug ?? ""}`;
  }
  return `/${locale.value}/${routePaths[item.route_name ?? ""] ?? ""}`;
}

async function loadNavigation() {
  try {
    configuredLinks.value = await getNavigation("main_navigation", locale.value);
  } catch {
    configuredLinks.value = [];
  }
}

onMounted(() => void loadNavigation());
watch(locale, () => void loadNavigation());
watch(() => route.fullPath, async () => {
  menuOpen.value = false;
  await nextTick();
  const heading = document.querySelector<HTMLElement>("#main-content h1");
  if (heading) {
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  }
});
</script>

<template>
  <div :class="['site-shell', { 'home-route': route.name === 'home' }]">
    <VSkipLink />
    <header class="site-header">
      <RouterLink
        class="brand"
        :to="`/${locale}/`"
        aria-label="VAV home"
      >
        <strong class="brand-wordmark">VAV</strong>
        <small>{{ t("brand.promise") }}</small>
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
        <template v-if="visibleConfiguredLinks.length">
          <template
            v-for="link in visibleConfiguredLinks"
            :key="link.id"
          >
            <a
              v-if="link.link_type === 'external'"
              :href="link.external_url ?? '#'"
              :target="link.open_in_new_tab ? '_blank' : undefined"
              :rel="link.open_in_new_tab ? 'noopener noreferrer' : undefined"
              @click="menuOpen = false"
            >
              {{ link.label }}
            </a>
            <RouterLink
              v-else
              :to="internalPath(link)"
              @click="menuOpen = false"
            >
              {{ link.label }}
            </RouterLink>
          </template>
        </template>
        <template v-else>
          <RouterLink
            v-for="link in fallbackLinks"
            :key="link.key"
            :to="`/${locale}/${link.path}`"
            @click="menuOpen = false"
          >
            {{ t(`nav.${link.key}`) }}
          </RouterLink>
        </template>
        <RouterLink
          class="cart-link"
          :to="`/${locale}/cart`"
          @click="menuOpen = false"
        >
          {{ t("commerce.cart") }}
        </RouterLink>
        <NotificationBell v-if="auth.user" />
        <GlobalCommandPalette />
        <RouterLink
          class="start-link"
          :to="auth.user ? `/${locale}/account` : `/${locale}/auth/register`"
          @click="menuOpen = false"
        >
          {{ auth.user ? t("nav.account") : t("nav.start") }}
          <span aria-hidden="true">↗</span>
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
      <RouterLink :to="`/${locale}/privacy`">
        隐私说明
      </RouterLink>
      <RouterLink
        v-if="auth.user"
        :to="`/${locale}/account/privacy`"
      >
        隐私中心
      </RouterLink>
      <RouterLink
        v-if="auth.user"
        :to="`/${locale}/account/tasks`"
      >
        任务中心
      </RouterLink>
      <RouterLink :to="`/${locale}/help`">
        帮助中心
      </RouterLink>
      <RouterLink :to="`/${locale}/account/orders`">
        {{ t("commerce.orders") }}
      </RouterLink>
    </footer>
  </div>
</template>
