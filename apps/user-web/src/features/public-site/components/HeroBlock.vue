<script setup lang="ts">
defineProps<{ data: Record<string, unknown> }>();
</script>

<template>
  <section class="cms-hero">
    <h1>{{ data.heading }}</h1>
    <p>{{ data.subheading }}</p>
  </section>
</template>
