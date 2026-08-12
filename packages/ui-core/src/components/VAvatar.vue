<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{ name?: string; size?: "default" | "large"; src?: string }>(),
  { size: "default" }
);

const initials = computed(() => {
  const value = (props.name ?? "").trim();
  if (!value) return "·";
  const ascii = /^[\x20-\x7F]+$/u.test(value);
  if (ascii) {
    return value
      .split(/\s+/u)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join("");
  }
  return value.slice(-2);
});
</script>

<template>
  <span
    class="v-avatar"
    :data-size="size"
    role="img"
    :aria-label="name || undefined"
  >
    <img
      v-if="src"
      :src="src"
      alt=""
    >
    <span
      v-else
      aria-hidden="true"
    >{{ initials }}</span>
  </span>
</template>
