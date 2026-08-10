<script setup lang="ts">
defineProps<{ data: Record<string, unknown> }>();
</script>

<template>
  <blockquote>
    <p>{{ data.quote }}</p>
    <cite v-if="data.attribution">{{ data.attribution }}</cite>
  </blockquote>
</template>
