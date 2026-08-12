<script setup lang="ts">
withDefaults(
  defineProps<{
    tone?: "neutral" | "brand" | "success" | "warning" | "danger" | "info";
    removable?: boolean;
    label: string;
  }>(),
  { tone: "neutral", removable: false }
);
defineEmits<{ remove: [] }>();
</script>

<template>
  <span
    class="v-chip"
    :data-tone="tone"
  >
    <span>{{ label }}</span>
    <button
      v-if="removable"
      type="button"
      class="v-chip__remove"
      :aria-label="`移除 ${label}`"
      @click="$emit('remove')"
    >
      <span aria-hidden="true">×</span>
    </button>
  </span>
</template>
