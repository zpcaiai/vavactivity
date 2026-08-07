<script setup lang="ts">
import type { ComponentPublicInstance } from "vue";

import RecommendationCard from "@/features/recommendations/components/RecommendationCard.vue";
import { useRecommendationExposure } from "@/features/recommendations/composables/useRecommendationExposure";
import type { RecommendationItem } from "@/features/recommendations/types";

const props = defineProps<{
  items: RecommendationItem[];
  /** Locale-prefixed base path, e.g. "/zh-CN/recommendations". */
  basePath?: string;
  preferencesPath?: string;
}>();

const emit = defineEmits<{
  (event: "open", itemId: string): void;
  (event: "not-relevant", itemId: string): void;
  (event: "interacted", itemId: string): void;
}>();

const { observeCard, unobserveCard, reportProfileOpened } = useRecommendationExposure({
  source: "recommendation_list"
});

const registrars = new Map<string, (element: Element | ComponentPublicInstance | null) => void>();

/**
 * Stable per-item ref callback.
 *
 * Mounting reports `card_impression`; the composable's IntersectionObserver
 * reports `card_visible` only after 1000ms of continuous visibility.
 */
function registerCard(itemId: string) {
  let registrar = registrars.get(itemId);
  if (!registrar) {
    let attached: Element | undefined;
    registrar = (element: Element | ComponentPublicInstance | null) => {
      if (element instanceof Element) {
        attached = element;
        observeCard(element, itemId);
        return;
      }
      unobserveCard(attached);
      attached = undefined;
    };
    registrars.set(itemId, registrar);
  }
  return registrar;
}

function detailPath(itemId: string) {
  return props.basePath ? `${props.basePath}/${itemId}` : undefined;
}

function open(itemId: string) {
  reportProfileOpened(itemId);
  emit("open", itemId);
}
</script>

<template>
  <ul class="recommendation-list">
    <li
      v-for="item in items"
      :key="item.recommendation_item_id"
      :ref="registerCard(item.recommendation_item_id)"
    >
      <RecommendationCard
        :item="item"
        :detail-path="detailPath(item.recommendation_item_id)"
        :preferences-path="preferencesPath"
        @open="open"
        @not-relevant="emit('not-relevant', $event)"
        @interacted="emit('interacted', $event)"
      />
    </li>
  </ul>
</template>

<style scoped>
.recommendation-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 1rem; }
</style>
