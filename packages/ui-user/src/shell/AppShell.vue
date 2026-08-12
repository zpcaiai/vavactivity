<script setup lang="ts">
withDefaults(defineProps<{ drawerOpen?: boolean; collapsed?: boolean }>(), {
  drawerOpen: false,
  collapsed: false
});
defineEmits<{ closeDrawer: [] }>();
</script>

<template>
  <div
    class="app-shell"
    :data-collapsed="collapsed || undefined"
    :data-drawer-open="drawerOpen || undefined"
  >
    <div class="app-shell__topbar">
      <slot name="topbar" />
    </div>

    <div
      v-if="drawerOpen"
      class="app-shell__scrim"
      @click="$emit('closeDrawer')"
    />

    <div class="app-shell__sidebar">
      <slot name="sidebar" />
    </div>

    <main
      id="main-content"
      class="app-shell__content"
    >
      <slot />
    </main>

    <div
      v-if="$slots.tabbar"
      class="app-shell__tabbar"
    >
      <slot name="tabbar" />
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  min-block-size: 100dvh;
  display: grid;
  grid-template-columns: var(--vav-layout-shell-sidebar-width) minmax(0, 1fr);
  grid-template-rows: var(--vav-layout-shell-header-height) minmax(0, 1fr);
  grid-template-areas: "topbar topbar" "sidebar content";
  background: var(--vav-color-surface);
  color: var(--vav-color-text);
}

.app-shell[data-collapsed] { grid-template-columns: var(--vav-layout-shell-sidebar-collapsed) minmax(0, 1fr); }

.app-shell__topbar {
  grid-area: topbar;
  position: sticky;
  inset-block-start: 0;
  z-index: var(--vav-layout-z-index-sticky);
  background: var(--vav-color-shell-surface);
  border-block-end: 1px solid var(--vav-color-shell-border);
}

.app-shell__sidebar {
  grid-area: sidebar;
  position: sticky;
  inset-block-start: var(--vav-layout-shell-header-height);
  block-size: calc(100dvh - var(--vav-layout-shell-header-height));
  overflow-y: auto;
  background: var(--vav-color-shell-surface);
  border-inline-end: 1px solid var(--vav-color-shell-border);
}

.app-shell__content {
  grid-area: content;
  min-inline-size: 0;
  padding: var(--vav-layout-shell-gutter);
  padding-block-end: calc(var(--vav-layout-shell-gutter) * 2);
}

.app-shell__scrim { display: none; }
.app-shell__tabbar { display: none; }

@media (max-width: 64rem) {
  .app-shell,
  .app-shell[data-collapsed] {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: "topbar" "content";
  }

  .app-shell__sidebar {
    position: fixed;
    inset-block: var(--vav-layout-shell-header-height) 0;
    inset-inline-start: 0;
    inline-size: min(20rem, 84vw);
    z-index: var(--vav-layout-z-index-drawer);
    transform: translateX(-102%);
    transition: transform var(--vav-duration-normal) var(--vav-easing-standard);
    box-shadow: var(--vav-component-elevation-overlay);
  }

  .app-shell[data-drawer-open] .app-shell__sidebar { transform: none; }

  .app-shell__scrim {
    display: block;
    position: fixed;
    inset: var(--vav-layout-shell-header-height) 0 0;
    z-index: calc(var(--vav-layout-z-index-drawer) - 1);
    background: var(--vav-color-overlay);
  }

  .app-shell__content {
    padding: var(--vav-layout-shell-gutter-compact);
    padding-block-end: calc(var(--vav-layout-shell-tabbar-height) + var(--vav-layout-safe-area-bottom) + var(--vav-space-6));
  }

  .app-shell__tabbar {
    display: block;
    position: fixed;
    inset-block-end: 0;
    inset-inline: 0;
    z-index: var(--vav-layout-z-index-tabbar);
    background: var(--vav-color-shell-surface);
    border-block-start: 1px solid var(--vav-color-shell-border);
    padding-block-end: var(--vav-layout-safe-area-bottom);
  }
}
</style>
