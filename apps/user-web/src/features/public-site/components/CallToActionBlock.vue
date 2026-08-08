<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ data: Record<string, unknown> }>();
const button = computed(() => props.data.button as { label?: string; href?: string } | undefined);
</script>

<template>
  <aside class="cms-call-to-action">
    <h2>{{ data.title }}</h2>
    <p>{{ data.description }}</p>
    <a
      v-if="button?.href"
      class="primary-button"
      :href="button.href"
    >{{ button.label }}</a>
  </aside>
</template>
