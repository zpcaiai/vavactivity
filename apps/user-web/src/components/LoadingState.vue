<script setup lang="ts">
withDefaults(defineProps<{ label?: string }>(), { label: "Loading" });
</script>

<template>
  <div
    class="inline-state"
    role="status"
    aria-live="polite"
  >
    <span
      class="spinner"
      aria-hidden="true"
    />
    <span>{{ label }}</span>
  </div>
</template>

