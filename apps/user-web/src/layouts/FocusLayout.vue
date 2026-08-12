<script setup lang="ts">
import { computed, nextTick, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { VSkipLink } from "@vav/ui-core";

import { useLocalePath } from "@/composables/useAppNavigation";

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const { localePath } = useLocalePath();

const title = computed(() => {
  const key = route.meta.focusTitleKey;
  return typeof key === "string" ? t(key) : t("shell.focusDefault");
});

function leave() {
  if (window.history.length > 1) {
    router.back();
    return;
  }
  void router.push(localePath("account/home"));
}

watch(
  () => route.fullPath,
  async () => {
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
  <div class="focus-shell">
    <VSkipLink />
    <header class="focus-shell__bar">
      <RouterLink
        class="focus-shell__brand"
        :to="localePath('account/home')"
      >
        <span
          class="focus-shell__mark"
          aria-hidden="true"
        >V</span>
        <strong>VAV</strong>
      </RouterLink>
      <p class="focus-shell__title">
        {{ title }}
      </p>
      <button
        class="focus-shell__leave"
        type="button"
        @click="leave"
      >
        {{ t("shell.leaveFocus") }}
      </button>
    </header>
    <main
      id="main-content"
      class="focus-shell__content"
    >
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.focus-shell { min-block-size: 100dvh; display: grid; grid-template-rows: var(--vav-layout-shell-header-height) minmax(0, 1fr); background: var(--vav-color-surface); color: var(--vav-color-text); }

.focus-shell__bar {
  position: sticky;
  inset-block-start: 0;
  z-index: var(--vav-layout-z-index-sticky);
  display: flex;
  align-items: center;
  gap: var(--vav-space-4);
  padding-inline: var(--vav-space-4);
  background: var(--vav-color-shell-surface);
  border-block-end: 1px solid var(--vav-color-shell-border);
}

.focus-shell__brand { display: flex; align-items: center; gap: var(--vav-space-2); color: var(--vav-color-text); text-decoration: none; }

.focus-shell__mark {
  display: inline-grid;
  place-items: center;
  inline-size: 2rem;
  block-size: 2rem;
  border-radius: var(--vav-radius-sm);
  background: var(--vav-color-action-primary);
  color: var(--vav-color-on-action);
  font-weight: var(--vav-font-weight-bold);
}

.focus-shell__title { flex: 1 1 auto; margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }

.focus-shell__leave {
  min-block-size: var(--vav-component-nav-item-height);
  padding-inline: var(--vav-space-3);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-radius-pill);
  background: var(--vav-color-surface-raised);
  color: var(--vav-color-text);
  cursor: pointer;
  font: inherit;
  font-size: var(--vav-font-size-sm);
}

.focus-shell__content { padding: var(--vav-layout-shell-gutter); }

@media (max-width: 48rem) {
  .focus-shell__title { display: none; }
  .focus-shell__content { padding: var(--vav-layout-shell-gutter-compact); }
}
</style>
