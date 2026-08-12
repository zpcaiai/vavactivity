<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { VSkipLink } from "@vav/ui-core";
import { AppMobileTabBar, AppShell, AppSidebar, AppTopbar } from "@vav/ui-user";

import GlobalCommandPalette from "@/features/experience/components/GlobalCommandPalette.vue";
import NotificationBell from "@/features/notifications/components/NotificationBell.vue";
import { useAppNavigation } from "@/composables/useAppNavigation";
import { useAuthStore } from "@/stores/auth";

const COLLAPSE_KEY = "vav.shell.collapsed";

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const auth = useAuthStore();
const { groups, tabs, activePath, locale, localePath } = useAppNavigation();

const drawerOpen = ref(false);
const collapsed = ref(false);
const accountMenuOpen = ref(false);

const accountLabel = computed(() => auth.user?.email ?? t("shell.account"));

onMounted(() => {
  try {
    collapsed.value = window.localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    collapsed.value = false;
  }
});

function toggleCollapse() {
  collapsed.value = !collapsed.value;
  try {
    window.localStorage.setItem(COLLAPSE_KEY, collapsed.value ? "1" : "0");
  } catch {
    // Preference persistence is best-effort only.
  }
}

async function signOut() {
  accountMenuOpen.value = false;
  try {
    await auth.logout();
  } catch {
    auth.clearSession();
  }
  await router.replace(localePath("auth/login"));
}

watch(
  () => route.fullPath,
  async () => {
    drawerOpen.value = false;
    accountMenuOpen.value = false;
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
  <AppShell
    :drawer-open="drawerOpen"
    :collapsed="collapsed"
    @close-drawer="drawerOpen = false"
  >
    <template #topbar>
      <VSkipLink />
      <AppTopbar
        :menu-label="t('shell.menu')"
        :drawer-open="drawerOpen"
        @toggle-drawer="drawerOpen = !drawerOpen"
      >
        <template #brand>
          <RouterLink
            class="shell-brand"
            :to="localePath('account/home')"
          >
            <span
              class="shell-brand__mark"
              aria-hidden="true"
            >V</span>
            <span class="shell-brand__text">
              <strong>VAV</strong>
              <small>{{ t("shell.memberSpace") }}</small>
            </span>
          </RouterLink>
        </template>

        <template #search>
          <GlobalCommandPalette />
        </template>

        <template #actions>
          <RouterLink
            class="shell-action"
            :to="localePath('help')"
          >
            {{ t("shell.help") }}
          </RouterLink>
          <RouterLink
            class="shell-action"
            to="/"
          >
            {{ t("common.language") }}
          </RouterLink>
          <NotificationBell v-if="auth.user" />
          <div class="shell-account">
            <button
              class="shell-account__button"
              type="button"
              :aria-expanded="accountMenuOpen"
              aria-haspopup="menu"
              @click="accountMenuOpen = !accountMenuOpen"
            >
              <span
                class="shell-account__avatar"
                aria-hidden="true"
              >{{ accountLabel.slice(0, 1).toUpperCase() }}</span>
              <span class="shell-account__label">{{ accountLabel }}</span>
            </button>
            <ul
              v-if="accountMenuOpen"
              class="shell-account__menu"
              role="menu"
            >
              <li role="none">
                <RouterLink
                  role="menuitem"
                  :to="localePath('account/profile')"
                >
                  {{ t("ia.items.profile") }}
                </RouterLink>
              </li>
              <li role="none">
                <RouterLink
                  role="menuitem"
                  :to="localePath('account/privacy')"
                >
                  {{ t("ia.items.privacy") }}
                </RouterLink>
              </li>
              <li role="none">
                <RouterLink
                  role="menuitem"
                  :to="localePath('')"
                >
                  {{ t("shell.publicSite") }}
                </RouterLink>
              </li>
              <li role="none">
                <button
                  role="menuitem"
                  type="button"
                  @click="signOut"
                >
                  {{ t("shell.signOut") }}
                </button>
              </li>
            </ul>
          </div>
        </template>
      </AppTopbar>
    </template>

    <template #sidebar>
      <AppSidebar
        :groups="groups"
        :collapsed="collapsed"
        :label="t('shell.primaryNavigation')"
        :collapse-label="t('shell.collapse')"
        :expand-label="t('shell.expand')"
        :active-path="activePath"
        @toggle-collapse="toggleCollapse"
        @navigate="drawerOpen = false"
      />
    </template>

    <template #tabbar>
      <AppMobileTabBar
        :items="tabs"
        :label="t('shell.primaryNavigation')"
        :active-path="activePath"
      />
    </template>

    <RouterView :key="locale" />
  </AppShell>
</template>

<style scoped>
.shell-brand { display: flex; align-items: center; gap: var(--vav-space-2); text-decoration: none; color: var(--vav-color-text); }

.shell-brand__mark {
  display: inline-grid;
  place-items: center;
  inline-size: 2rem;
  block-size: 2rem;
  border-radius: var(--vav-radius-sm);
  background: var(--vav-color-action-primary);
  color: var(--vav-color-on-action);
  font-weight: var(--vav-font-weight-bold);
}

.shell-brand__text { display: grid; line-height: var(--vav-line-height-tight); }
.shell-brand__text small { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); }

.shell-action {
  display: inline-flex;
  align-items: center;
  min-block-size: var(--vav-component-nav-item-height);
  padding-inline: var(--vav-space-2);
  border-radius: var(--vav-radius-sm);
  color: var(--vav-color-text-muted);
  text-decoration: none;
  font-size: var(--vav-font-size-sm);
}

.shell-action:hover { background: var(--vav-color-interactive-hover); color: var(--vav-color-text); }

.shell-account { position: relative; }

.shell-account__button {
  display: inline-flex;
  align-items: center;
  gap: var(--vav-space-2);
  min-block-size: var(--vav-component-nav-item-height);
  padding-inline: var(--vav-space-2);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-radius-pill);
  background: var(--vav-color-surface-raised);
  color: var(--vav-color-text);
  cursor: pointer;
  font: inherit;
  font-size: var(--vav-font-size-sm);
}

.shell-account__avatar {
  display: inline-grid;
  place-items: center;
  inline-size: 1.75rem;
  block-size: 1.75rem;
  border-radius: var(--vav-radius-pill);
  background: var(--vav-color-surface-brand);
  color: var(--vav-color-action-primary);
  font-weight: var(--vav-font-weight-bold);
}

.shell-account__label { max-inline-size: 12rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.shell-account__menu {
  position: absolute;
  inset-block-start: calc(100% + var(--vav-space-2));
  inset-inline-end: 0;
  z-index: var(--vav-layout-z-index-drawer);
  min-inline-size: 12rem;
  margin: 0;
  padding: var(--vav-space-2);
  list-style: none;
  display: grid;
  gap: 2px;
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-radius-md);
  background: var(--vav-color-surface-raised);
  box-shadow: var(--vav-component-elevation-overlay);
}

.shell-account__menu :where(a, button) {
  display: block;
  inline-size: 100%;
  padding: var(--vav-space-2) var(--vav-space-3);
  border: 0;
  border-radius: var(--vav-radius-sm);
  background: none;
  color: var(--vav-color-text);
  text-align: start;
  text-decoration: none;
  font: inherit;
  font-size: var(--vav-font-size-sm);
  cursor: pointer;
}

.shell-account__menu :where(a, button):hover { background: var(--vav-color-interactive-hover); }

@media (max-width: 48rem) {
  .shell-account__label,
  .shell-brand__text small { display: none; }
}
</style>
