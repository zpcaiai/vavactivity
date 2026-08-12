<script setup lang="ts">
export interface VTabItem {
  key: string;
  label: string;
  to: string;
  badge?: number | string;
  disabled?: boolean;
}

defineProps<{ items: VTabItem[]; label: string }>();
</script>

<template>
  <nav
    class="v-tabs"
    :aria-label="label"
  >
    <ul>
      <li
        v-for="item in items"
        :key="item.key"
      >
        <RouterLink
          class="v-tabs__link"
          :to="item.to"
          :aria-disabled="item.disabled || undefined"
        >
          <span>{{ item.label }}</span>
          <span
            v-if="item.badge !== undefined && item.badge !== 0"
            class="v-tabs__badge"
          >{{ item.badge }}</span>
        </RouterLink>
      </li>
    </ul>
  </nav>
</template>
