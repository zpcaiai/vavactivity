<script setup lang="ts">
defineProps<{ menuLabel: string; drawerOpen: boolean }>();
defineEmits<{ toggleDrawer: [] }>();
</script>

<template>
  <div class="app-topbar">
    <button
      class="app-topbar__menu"
      type="button"
      :aria-label="menuLabel"
      :aria-expanded="drawerOpen"
      @click="$emit('toggleDrawer')"
    >
      <span aria-hidden="true" />
      <span aria-hidden="true" />
      <span aria-hidden="true" />
    </button>

    <div class="app-topbar__brand">
      <slot name="brand" />
    </div>

    <div class="app-topbar__search">
      <slot name="search" />
    </div>

    <div class="app-topbar__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.app-topbar {
  block-size: 100%;
  display: flex;
  align-items: center;
  gap: var(--vav-space-3);
  padding-inline: var(--vav-space-4);
}

.app-topbar__brand { display: flex; align-items: center; gap: var(--vav-space-2); }
.app-topbar__search { flex: 1 1 auto; min-inline-size: 0; display: flex; justify-content: center; }
.app-topbar__actions { display: flex; align-items: center; gap: var(--vav-space-2); }

.app-topbar__menu {
  display: none;
  flex-direction: column;
  gap: 4px;
  justify-content: center;
  min-inline-size: var(--vav-component-touch-target-minimum);
  min-block-size: var(--vav-component-touch-target-minimum);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-radius-sm);
  background: var(--vav-color-surface-raised);
  cursor: pointer;
  padding-inline: var(--vav-space-2);
}

.app-topbar__menu span { display: block; block-size: 2px; background: var(--vav-color-text); }

@media (max-width: 64rem) {
  .app-topbar__menu { display: flex; }
  .app-topbar__search { display: none; }
}
</style>
