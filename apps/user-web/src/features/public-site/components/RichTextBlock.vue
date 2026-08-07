<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ data: Record<string, unknown> }>();

function collectText(value: unknown): string[] {
  if (typeof value === "string") {
    return [value];
  }
  if (Array.isArray(value)) {
    return value.flatMap(collectText);
  }
  if (value && typeof value === "object") {
    return Object.values(value).flatMap(collectText);
  }
  return [];
}

const paragraphs = computed(() => collectText(props.data.document));
</script>

<template>
  <div class="cms-rich-text">
    <p
      v-for="(paragraph, index) in paragraphs"
      :key="index"
    >
      {{ paragraph }}
    </p>
  </div>
</template>
