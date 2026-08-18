<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { VSkipLink } from "@vav/ui-core";

import GlobalCommandPalette from "@/features/experience/components/GlobalCommandPalette.vue";
import NotificationBell from "@/features/notifications/components/NotificationBell.vue";
import { getNavigation, type PublicNavigationItem } from "@/features/public-site/api/content";
import { useAppNavigation } from "@/composables/useAppNavigation";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const { t } = useI18n();
const auth = useAuthStore();
const { publicLinks, locale, localePath } = useAppNavigation();

const menuOpen = ref(false);
const currentYear = new Date().getFullYear();
const configuredLinks = ref<PublicNavigationItem[]>([]);

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
  membership: "membership",
  ai: "ai-assistant"
};

/**
 * Content-managed navigation wins when the CMS provides it; the IA module is
 * the fallback so the header is never empty and never drifts from the routes
 * that actually exist.
 */
interface HeaderLink {
  key: string;
  label: string;
  to: string;
  external?: string;
  newTab?: boolean;
}

const links = computed<HeaderLink[]>(() => {
  const configured = configuredLinks.value.filter(
    (item) => !item.required_auth || Boolean(auth.user)
  );
  if (!configured.length) return publicLinks.value;
  return configured.map((item) => ({
    key: String(item.id),
    label: item.label,
    to:
      item.link_type === "content"
        ? localePath(item.target_slug ?? "")
        : localePath(routePaths[item.route_name ?? ""] ?? ""),
    external: item.link_type === "external" ? item.external_url ?? "#" : undefined,
    newTab: item.open_in_new_tab
  }));
});

const footerGroups = computed(() => [
  {
    key: "services",
    label: t("footer.services"),
    links: [
      { label: t("ia.public.activities"), to: localePath("activities") },
      { label: t("ia.public.courses"), to: localePath("courses") },
      { label: t("ia.public.counseling"), to: localePath("counseling") },
      { label: t("ia.public.membership"), to: localePath("membership") }
    ]
  },
  {
    key: "about",
    label: t("footer.about"),
    links: [
      { label: t("ia.public.about"), to: localePath("about") },
      { label: t("ia.public.stories"), to: localePath("stories") },
      { label: t("ia.public.articles"), to: localePath("articles") },
      { label: t("footer.contact"), to: localePath("contact") }
    ]
  },
  {
    key: "trust",
    label: t("footer.trust"),
    links: [
      { label: t("footer.privacy"), to: localePath("privacy") },
      { label: t("footer.terms"), to: localePath("terms") },
      { label: t("footer.refund"), to: localePath("refund-policy") },
      { label: t("footer.aiDisclaimer"), to: localePath("ai-disclaimer") },
      { label: t("footer.safety"), to: localePath("safety-support") }
    ]
  },
  {
    key: "support",
    label: t("footer.support"),
    links: [
      { label: t("footer.help"), to: localePath("help") },
      { label: t("footer.search"), to: localePath("search") }
    ]
  }
]);

async function loadNavigation() {
  try {
    configuredLinks.value = await getNavigation("main_navigation", locale.value);
  } catch {
    configuredLinks.value = [];
  }
}

onMounted(() => void loadNavigation());
watch(locale, () => void loadNavigation());
watch(
  () => route.fullPath,
  async () => {
    menuOpen.value = false;
    await nextTick();
    const heading = document.querySelector<HTMLElement>("#main-content h1");
    if (heading) {
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
    }
  }
);
</script>

<template>
  <div :class="['site-shell', { 'home-route': route.name === 'home' }]">
    <VSkipLink />

    <header class="site-header">
      <RouterLink
        class="site-header__brand"
        :to="localePath('')"
        aria-label="VAV"
      >
        <span
          class="site-header__mark"
          aria-hidden="true"
        >V</span>
        <span class="site-header__wordmark">
          <strong>VAV</strong>
          <small>{{ t("brand.promise") }}</small>
        </span>
      </RouterLink>

      <button
        class="site-header__menu"
        type="button"
        :aria-label="t('nav.menu')"
        :aria-expanded="menuOpen"
        @click="menuOpen = !menuOpen"
      >
        <span aria-hidden="true" />
        <span aria-hidden="true" />
        <span aria-hidden="true" />
      </button>

      <nav
        :class="['site-nav', { open: menuOpen }]"
        :aria-label="t('nav.primary')"
      >
        <template
          v-for="link in links"
          :key="link.key"
        >
          <a
            v-if="link.external"
            :href="link.external"
            :target="link.newTab ? '_blank' : undefined"
            :rel="link.newTab ? 'noopener noreferrer' : undefined"
            @click="menuOpen = false"
          >{{ link.label }}</a>
          <RouterLink
            v-else
            :to="link.to"
            @click="menuOpen = false"
          >
            {{ link.label }}
          </RouterLink>
        </template>
      </nav>

      <div class="site-header__actions">
        <GlobalCommandPalette />
        <RouterLink
          class="site-header__cart"
          :to="localePath('cart')"
        >
          {{ t("commerce.cart") }}
        </RouterLink>
        <NotificationBell v-if="auth.user" />
        <RouterLink
          class="site-header__cta"
          :to="auth.user ? localePath('account/home') : localePath('auth/register')"
        >
          {{ auth.user ? t("shell.memberSpace") : t("nav.start") }}
          <span aria-hidden="true">↗</span>
        </RouterLink>
        <RouterLink
          class="site-header__language"
          to="/"
        >
          {{ t("common.language") }}
        </RouterLink>
      </div>
    </header>

    <main id="main-content">
      <RouterView />
    </main>

    <footer class="site-footer">
      <div class="site-footer__inner">
        <div class="site-footer__brand">
          <span
            class="site-header__mark"
            aria-hidden="true"
          >V</span>
          <div>
            <strong>VAV</strong>
            <p>{{ t("brand.promise") }}</p>
          </div>
        </div>

        <nav
          class="site-footer__groups"
          :aria-label="t('footer.navigation')"
        >
          <section
            v-for="group in footerGroups"
            :key="group.key"
          >
            <h2>{{ group.label }}</h2>
            <ul>
              <li
                v-for="link in group.links"
                :key="link.to"
              >
                <RouterLink :to="link.to">
                  {{ link.label }}
                </RouterLink>
              </li>
            </ul>
          </section>
        </nav>
      </div>

      <div class="site-footer__meta">
        <p class="site-footer__legal">
          © {{ currentYear }} VAV · {{ t("footer.legal") }}
        </p>
      </div>
    </footer>
  </div>
</template>
