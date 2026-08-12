<script setup lang="ts">
import type { AppNavGroup } from "../types";

defineProps<{
  groups: AppNavGroup[];
  collapsed: boolean;
  label: string;
  collapseLabel: string;
  expandLabel: string;
  activePath: string;
}>();
defineEmits<{ toggleCollapse: []; navigate: [] }>();

function isActive(activePath: string, to: string, exact?: boolean) {
  return exact ? activePath === to : activePath === to || activePath.startsWith(`${to}/`);
}
</script>

<template>
  <nav
    class="app-sidebar"
    :aria-label="label"
  >
    <ul class="app-sidebar__groups">
      <li
        v-for="group in groups"
        :key="group.key"
        class="app-sidebar__group"
      >
        <RouterLink
          class="app-sidebar__group-link"
          :to="group.to"
          :data-active="isActive(activePath, group.to) || undefined"
          :title="collapsed ? group.label : undefined"
          @click="$emit('navigate')"
        >
          <span
            class="app-sidebar__glyph"
            aria-hidden="true"
          >{{ group.glyph }}</span>
          <span class="app-sidebar__label">{{ group.label }}</span>
        </RouterLink>

        <ul
          v-if="!collapsed && group.items.length"
          class="app-sidebar__items"
        >
          <li
            v-for="item in group.items"
            :key="item.key"
          >
            <RouterLink
              class="app-sidebar__item"
              :to="item.to"
              :data-active="isActive(activePath, item.to, item.exact) || undefined"
              :data-critical="item.critical || undefined"
              @click="$emit('navigate')"
            >
              <span>{{ item.label }}</span>
              <span
                v-if="item.badge"
                class="app-sidebar__badge"
              >{{ item.badge > 99 ? "99+" : item.badge }}</span>
            </RouterLink>
          </li>
        </ul>
      </li>
    </ul>

    <button
      class="app-sidebar__collapse"
      type="button"
      @click="$emit('toggleCollapse')"
    >
      <span aria-hidden="true">{{ collapsed ? "»" : "«" }}</span>
      <span class="app-sidebar__label">{{ collapsed ? expandLabel : collapseLabel }}</span>
    </button>
  </nav>
</template>

<style scoped>
.app-sidebar {
  block-size: 100%;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: var(--vav-space-4);
  padding: var(--vav-space-4) var(--vav-space-3);
}

.app-sidebar__groups { display: grid; gap: var(--vav-space-4); margin: 0; padding: 0; list-style: none; }
.app-sidebar__group { display: grid; gap: var(--vav-space-1); }

.app-sidebar__group-link,
.app-sidebar__item,
.app-sidebar__collapse {
  display: flex;
  align-items: center;
  gap: var(--vav-component-nav-item-gap);
  min-block-size: var(--vav-component-nav-item-height);
  padding-inline: var(--vav-component-nav-item-padding-inline);
  border-radius: var(--vav-component-nav-item-radius);
  color: var(--vav-color-shell-text);
  text-decoration: none;
  font-size: var(--vav-font-size-sm);
}

.app-sidebar__group-link { font-weight: var(--vav-font-weight-semibold); font-size: var(--vav-font-size-md); }
.app-sidebar__group-link:hover,
.app-sidebar__item:hover,
.app-sidebar__collapse:hover { background: var(--vav-color-interactive-hover); }
.app-sidebar__group-link[data-active] { background: var(--vav-color-interactive-selected); color: var(--vav-color-action-primary); }
.app-sidebar__items { display: grid; gap: 2px; margin: 0; padding-inline-start: var(--vav-space-8); list-style: none; }
.app-sidebar__item { justify-content: space-between; }
.app-sidebar__item[data-active] { background: var(--vav-color-interactive-selected); color: var(--vav-color-action-primary); font-weight: var(--vav-font-weight-semibold); }
.app-sidebar__item[data-critical] { color: var(--vav-color-danger); }

.app-sidebar__glyph {
  display: inline-grid;
  place-items: center;
  inline-size: 1.75rem;
  block-size: 1.75rem;
  border-radius: var(--vav-radius-sm);
  background: var(--vav-color-surface-soft);
  flex: none;
}

.app-sidebar__badge {
  min-inline-size: 1.25rem;
  padding-inline: 0.3rem;
  border-radius: var(--vav-radius-pill);
  background: var(--vav-color-action-primary);
  color: var(--vav-color-on-action);
  font-size: var(--vav-font-size-xs);
  font-weight: var(--vav-font-weight-bold);
  text-align: center;
}

.app-sidebar__collapse {
  border: 1px solid var(--vav-color-border);
  background: var(--vav-color-surface-raised);
  cursor: pointer;
  inline-size: 100%;
  font: inherit;
  font-size: var(--vav-font-size-sm);
}

.app-shell[data-collapsed] .app-sidebar__label { display: none; }

@media (max-width: 64rem) {
  .app-sidebar__collapse { display: none; }
}
</style>
