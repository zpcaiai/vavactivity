<script setup lang="ts">
defineProps<{ data: Record<string, unknown>; type: string }>();
</script>

<template>
  <section class="cms-collection">
    <p class="eyebrow">
      {{ type.replaceAll("_", " ") }}
    </p>
    <h2 v-if="data.title">
      {{ data.title }}
    </h2>
  </section>
</template>
