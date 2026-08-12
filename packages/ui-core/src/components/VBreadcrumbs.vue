<script setup lang="ts">
export interface VBreadcrumbItem {
  label: string;
  to?: string;
}

withDefaults(defineProps<{ items: VBreadcrumbItem[]; label?: string }>(), { label: "面包屑" });
</script>

<template>
  <nav
    class="v-breadcrumbs"
    :aria-label="label"
  >
    <ol>
      <li
        v-for="(item, index) in items"
        :key="`${item.label}-${index}`"
      >
        <RouterLink
          v-if="item.to && index < items.length - 1"
          :to="item.to"
        >
          {{ item.label }}
        </RouterLink>
        <span
          v-else
          :aria-current="index === items.length - 1 ? 'page' : undefined"
        >{{ item.label }}</span>
      </li>
    </ol>
  </nav>
</template>
