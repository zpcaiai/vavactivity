<script setup lang="ts">
import type { AppTabItem } from "../types";

defineProps<{ items: AppTabItem[]; label: string; activePath: string }>();
</script>

<template>
  <nav
    class="app-tabbar"
    :aria-label="label"
  >
    <RouterLink
      v-for="item in items"
      :key="item.key"
      class="app-tabbar__item"
      :to="item.to"
      :data-active="(activePath === item.to || activePath.startsWith(`${item.to}/`)) || undefined"
    >
      <span
        class="app-tabbar__glyph"
        aria-hidden="true"
      >{{ item.glyph }}</span>
      <span class="app-tabbar__label">{{ item.label }}</span>
      <span
        v-if="item.badge"
        class="app-tabbar__dot"
        aria-hidden="true"
      />
    </RouterLink>
  </nav>
</template>

<style scoped>
.app-tabbar {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: 1fr;
  block-size: var(--vav-layout-shell-tabbar-height);
}

.app-tabbar__item {
  position: relative;
  display: grid;
  place-items: center;
  gap: 2px;
  color: var(--vav-color-text-muted);
  text-decoration: none;
  font-size: var(--vav-font-size-xs);
}

.app-tabbar__item[data-active] { color: var(--vav-color-action-primary); font-weight: var(--vav-font-weight-semibold); }
.app-tabbar__glyph { font-size: var(--vav-font-size-lg); line-height: 1; }

.app-tabbar__dot {
  position: absolute;
  inset-block-start: 0.35rem;
  inset-inline-end: 30%;
  inline-size: 0.5rem;
  block-size: 0.5rem;
  border-radius: var(--vav-radius-pill);
  background: var(--vav-color-danger);
}
</style>
