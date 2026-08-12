<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch, watchEffect } from "vue";
import { useRoute, useRouter } from "vue-router";
import { VSkipLink } from "@vav/ui-core";

import { adminLocales, type AdminLocale, useAdminLocale } from "@/i18n";
import {
  adminGroups,
  landingPath,
  moduleForPath,
  type AdminModule
} from "@/navigation/admin-nav";
import { useAdminAuthStore } from "@/stores/admin-auth";

const COLLAPSE_KEY = "vav.admin.sidebar.collapsed";

const route = useRoute();
const router = useRouter();
const auth = useAdminAuthStore();
const { locale, setLocale, t } = useAdminLocale();

const collapsed = ref(false);
const drawerOpen = ref(false);
const filter = ref("");
const openGroups = ref<Record<string, boolean>>({});
const signingOut = ref(false);

const can = (permission: string) => auth.hasPermission(permission);
const pageTitle = computed(() => String(route.meta.title ?? t("shell.workspace")));
const current = computed(() => moduleForPath(route.path));

/**
 * Only modules the operator can actually open are rendered. A section that is
 * hidden here is also rejected by the router guard and by the API, so an
 * operator never sees a link that leads to a 403.
 */
const visibleGroups = computed(() => {
  const needle = filter.value.trim().toLowerCase();
  return adminGroups
    .map((group) => ({
      ...group,
      label: t(group.labelKey),
      modules: group.modules
        .filter((module) => !module.permission || can(module.permission))
        .map((module) => ({ module, label: t(module.labelKey), to: landingPath(module, can) }))
        .filter((entry) => !needle || entry.label.toLowerCase().includes(needle))
    }))
    .filter((group) => group.modules.length);
});

const sections = computed(() => {
  const module = current.value?.module;
  if (!module?.sections.length) return [];
  return module.sections
    .filter((item) => !item.permission || can(item.permission))
    .map((item) => ({
      key: item.key,
      label: t(item.labelKey),
      to: `${module.base}/${item.key}`
    }));
});

const activeSection = computed(() => {
  const module = current.value?.module;
  if (!module) return "";
  const rest = route.path.slice(module.base.length + 1);
  return rest.split("/")[0] ?? "";
});

const breadcrumbs = computed(() => {
  const entry = current.value;
  if (!entry) return [{ label: t("shell.workspace"), to: "/admin/dashboard" }];
  const trail = [
    { label: t("shell.workspace"), to: "/admin/dashboard" },
    { label: t(entry.group.labelKey) },
    { label: t(entry.module.labelKey), to: landingPath(entry.module, can) }
  ];
  const section = sections.value.find((item) => item.key === activeSection.value);
  if (section) trail.push({ label: section.label });
  return trail;
});

function isModuleActive(module: AdminModule) {
  return route.path === module.base || route.path.startsWith(`${module.base}/`);
}

function toggleGroup(key: string) {
  openGroups.value = { ...openGroups.value, [key]: !isGroupOpen(key) };
}

function isGroupOpen(key: string) {
  if (key in openGroups.value) return openGroups.value[key];
  return current.value ? current.value.group.key === key : key === "workbench";
}

function toggleCollapse() {
  collapsed.value = !collapsed.value;
  try {
    window.localStorage.setItem(COLLAPSE_KEY, collapsed.value ? "1" : "0");
  } catch {
    // Preference persistence is best-effort only.
  }
}

function changeLocale(value: string) {
  if (adminLocales.includes(value as AdminLocale)) setLocale(value as AdminLocale);
}

async function logout() {
  signingOut.value = true;
  try {
    await auth.logout();
  } catch {
    // Never retain a bearer token locally merely because the network failed.
    auth.clearSession();
  } finally {
    signingOut.value = false;
    await router.replace({ name: "admin-login" });
  }
}

onMounted(() => {
  try {
    collapsed.value = window.localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    collapsed.value = false;
  }
});

watchEffect(() => {
  document.documentElement.lang = locale.value;
});

watch(
  () => route.fullPath,
  async () => {
    drawerOpen.value = false;
    await nextTick();
    const heading = document.querySelector<HTMLElement>("#admin-main h1");
    if (heading) {
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
    }
  }
);
</script>

<template>
  <div
    class="admin-shell"
    :data-collapsed="collapsed || undefined"
    :data-drawer-open="drawerOpen || undefined"
  >
    <VSkipLink target="admin-main" />

    <header class="admin-topbar">
      <button
        class="admin-topbar__menu"
        type="button"
        :aria-label="t('shell.menu')"
        :aria-expanded="drawerOpen"
        @click="drawerOpen = !drawerOpen"
      >
        <span aria-hidden="true" />
        <span aria-hidden="true" />
        <span aria-hidden="true" />
      </button>

      <RouterLink
        class="admin-brand"
        to="/admin/dashboard"
      >
        <span
          class="admin-brand__mark"
          aria-hidden="true"
        >V</span>
        <span class="admin-brand__text">
          <strong>VAV</strong>
          <small>{{ t("shell.workspace") }}</small>
        </span>
      </RouterLink>

      <div class="admin-topbar__spacer" />

      <label class="admin-locale">
        <span class="sr-only">{{ t("shell.language") }}</span>
        <select
          data-testid="admin-locale-select"
          :value="locale"
          @change="changeLocale(($event.target as HTMLSelectElement).value)"
        >
          <option value="zh-CN">简体中文</option>
          <option value="zh-TW">繁體中文</option>
          <option value="en">English</option>
        </select>
      </label>

      <div class="admin-operator">
        <span
          class="admin-operator__dot"
          aria-hidden="true"
        />
        <span class="admin-operator__text">
          <strong>{{ auth.user?.email }}</strong>
          <small>{{ t("shell.authorizedSession") }}</small>
        </span>
      </div>

      <button
        class="admin-signout"
        type="button"
        :disabled="signingOut"
        @click="logout"
      >
        {{ signingOut ? t("shell.signingOut") : t("shell.logout") }}
      </button>
    </header>

    <div
      v-if="drawerOpen"
      class="admin-scrim"
      @click="drawerOpen = false"
    />

    <nav
      class="admin-sidebar"
      :aria-label="t('shell.navigation')"
    >
      <label
        v-if="!collapsed"
        class="admin-sidebar__filter"
      >
        <span class="sr-only">{{ t("shell.filterModules") }}</span>
        <input
          v-model="filter"
          type="search"
          :placeholder="t('shell.filterModules')"
        >
      </label>

      <ul class="admin-sidebar__groups">
        <li
          v-for="group in visibleGroups"
          :key="group.key"
        >
          <button
            class="admin-sidebar__group"
            type="button"
            :aria-expanded="isGroupOpen(group.key)"
            @click="toggleGroup(group.key)"
          >
            <span
              class="admin-sidebar__glyph"
              aria-hidden="true"
            >{{ group.glyph }}</span>
            <span class="admin-sidebar__label">{{ group.label }}</span>
            <span
              class="admin-sidebar__chevron"
              aria-hidden="true"
            >{{ isGroupOpen(group.key) ? "▾" : "▸" }}</span>
          </button>

          <ul
            v-if="isGroupOpen(group.key) || Boolean(filter.trim())"
            class="admin-sidebar__modules"
          >
            <li
              v-for="entry in group.modules"
              :key="entry.module.key"
            >
              <RouterLink
                :to="entry.to"
                :data-active="isModuleActive(entry.module) || undefined"
                :title="collapsed ? entry.label : undefined"
              >
                {{ entry.label }}
              </RouterLink>
            </li>
          </ul>
        </li>
      </ul>

      <button
        class="admin-sidebar__collapse"
        type="button"
        @click="toggleCollapse"
      >
        <span aria-hidden="true">{{ collapsed ? "»" : "«" }}</span>
        <span class="admin-sidebar__label">{{ collapsed ? t("shell.expand") : t("shell.collapse") }}</span>
      </button>
    </nav>

    <main
      id="admin-main"
      class="admin-main"
    >
      <nav
        class="admin-breadcrumbs"
        :aria-label="t('shell.breadcrumbs')"
      >
        <ol>
          <li
            v-for="(crumb, index) in breadcrumbs"
            :key="`${crumb.label}-${index}`"
          >
            <RouterLink
              v-if="crumb.to && index < breadcrumbs.length - 1"
              :to="crumb.to"
            >
              {{ crumb.label }}
            </RouterLink>
            <span
              v-else
              :aria-current="index === breadcrumbs.length - 1 ? 'page' : undefined"
            >{{ crumb.label }}</span>
          </li>
        </ol>
      </nav>

      <header class="admin-page-header">
        <div>
          <p class="admin-kicker">
            {{ current ? t(current.group.labelKey) : t("shell.operations") }}
          </p>
          <h1>{{ pageTitle }}</h1>
        </div>
      </header>

      <nav
        v-if="sections.length > 1"
        class="admin-sections"
        :aria-label="t('shell.sections')"
      >
        <RouterLink
          v-for="item in sections"
          :key="item.key"
          :to="item.to"
          :data-active="item.key === activeSection || undefined"
        >
          {{ item.label }}
        </RouterLink>
      </nav>

      <div class="admin-page-body">
        <RouterView />
      </div>
    </main>
  </div>
</template>
