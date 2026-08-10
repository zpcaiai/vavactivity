<script setup lang="ts">
import { computed } from "vue";
import { resolveApiBaseUrl } from "@/config/api";

const props = defineProps<{ data: Record<string, unknown> }>();
const baseUrl = resolveApiBaseUrl();
const source = computed(() =>
  props.data.media_id
    ? `${baseUrl}/public/media/${String(props.data.media_id)}?variant=medium`
    : ""
);
const alt = computed(() =>
  props.data.decorative ? "" : String(props.data.alt_text ?? "")
);
</script>

<template>
  <img
    v-if="source"
    class="cms-content-image"
    :src="source"
    :alt="alt"
  >
</template>
