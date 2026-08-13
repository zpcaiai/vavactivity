<script setup lang="ts">
import { VAvatar, VCard, VChip } from "@vav/ui-core";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { FrozenCandidate } from "@/features/post-event/types";

const props = defineProps<{
  candidate: FrozenCandidate;
  selected: boolean;
  /** True when the ceiling is reached and this card is not already chosen. */
  blocked: boolean;
  disabled: boolean;
}>();

const emit = defineEmits<{ (event: "toggle", userId: string): void }>();

const { t } = useI18n();

const unavailable = computed(() => props.disabled || (props.blocked && !props.selected));

function activate() {
  if (unavailable.value) return;
  emit("toggle", props.candidate.user_id);
}
</script>

<template>
  <VCard
    class="candidate-card"
    :data-selected="selected ? 'true' : 'false'"
  >
    <button
      type="button"
      class="candidate-card__button"
      role="checkbox"
      :aria-checked="selected"
      :aria-describedby="blocked && !selected ? 'selection-limit-hint' : undefined"
      :disabled="unavailable"
      @click="activate"
    >
      <VAvatar
        :name="candidate.display_name"
        size="large"
      />
      <span class="candidate-card__name">{{ candidate.display_name }}</span>
      <VChip
        v-if="selected"
        tone="brand"
        :label="t('postEvent.selection.chosen')"
      />
    </button>
  </VCard>
</template>

<style scoped>
.candidate-card {
  transition: border-color var(--vav-motion-fast, 120ms) ease;
}

.candidate-card[data-selected="true"] {
  border-color: var(--vav-color-brand-border);
  background: var(--vav-color-brand-surface);
}

.candidate-card__button {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--vav-space-3);
  width: 100%;
  padding: var(--vav-space-4);
  border: 0;
  border-radius: var(--vav-radius-md);
  background: transparent;
  color: var(--vav-color-text-primary);
  cursor: pointer;
  /* Onsite and mobile use: a comfortable target, not a dense list row. */
  min-height: 9rem;
}

.candidate-card__button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.candidate-card__button:focus-visible {
  outline: var(--vav-focus-ring-width) solid var(--vav-color-focus-ring);
  outline-offset: 2px;
}

.candidate-card__name {
  font-weight: var(--vav-font-weight-medium);
}
</style>
