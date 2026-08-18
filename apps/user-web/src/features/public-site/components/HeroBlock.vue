<script setup lang="ts">
defineProps<{ data: Record<string, unknown> }>();
</script>

<template>
  <!-- `h2`, not `h1`: the page that hosts this block already owns the page
       heading, and a CMS block emitting a second `h1` breaks the outline and
       inherits display-size type it was never meant to have. -->
  <section class="cms-hero">
    <h2>{{ data.heading }}</h2>
    <p v-if="data.subheading">
      {{ data.subheading }}
    </p>
  </section>
</template>
