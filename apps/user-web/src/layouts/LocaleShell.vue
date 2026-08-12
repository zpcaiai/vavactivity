<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

import AppLayout from "@/layouts/AppLayout.vue";
import FocusLayout from "@/layouts/FocusLayout.vue";
import PublicLayout from "@/layouts/PublicLayout.vue";

/**
 * All locale-prefixed routes share one parent record so that route matching
 * stays unambiguous — three sibling records with the same path made
 * `/{locale}/` resolve to whichever record happened to be registered first.
 * The shell picks the layout from `meta.layout`; each layout renders the child
 * `<RouterView>` itself.
 */
const route = useRoute();

const layout = computed(() => {
  const value = route.meta.layout;
  return value === "app" || value === "focus" ? value : "public";
});
</script>

<template>
  <AppLayout v-if="layout === 'app'" />
  <FocusLayout v-else-if="layout === 'focus'" />
  <PublicLayout v-else />
</template>
