<script setup lang="ts">
defineProps<{ title: string; description: string }>();
</script>

<template>
  <div class="empty-state">
    <span
      class="empty-symbol"
      aria-hidden="true"
    >○</span>
    <h2>{{ title }}</h2>
    <p>{{ description }}</p>
    <slot />
  </div>
</template>

