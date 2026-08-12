<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string;
    value: string | number;
    hint?: string;
    tone?: "default" | "success" | "warning" | "danger" | "info" | "brand";
    to?: string;
  }>(),
  { tone: "default" }
);
</script>

<template>
  <component
    :is="to ? 'RouterLink' : 'div'"
    class="v-metric"
    :data-tone="tone"
    :to="to"
  >
    <span class="v-metric__value">{{ value }}</span>
    <span class="v-metric__label">{{ label }}</span>
    <span
      v-if="hint"
      class="v-metric__hint"
    >{{ hint }}</span>
  </component>
</template>
