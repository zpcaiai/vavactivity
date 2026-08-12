<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{ value: number; max?: number; label: string; showValue?: boolean }>(),
  { max: 100, showValue: true }
);

const percent = computed(() => {
  if (props.max <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((props.value / props.max) * 100)));
});
</script>

<template>
  <div class="v-progress">
    <div class="v-progress__meta">
      <span>{{ label }}</span>
      <span v-if="showValue">{{ value }} / {{ max }}</span>
    </div>
    <div
      class="v-progress__track"
      role="progressbar"
      :aria-valuenow="value"
      :aria-valuemin="0"
      :aria-valuemax="max"
      :aria-label="label"
    >
      <span
        class="v-progress__fill"
        :style="{ inlineSize: `${percent}%` }"
      />
    </div>
  </div>
</template>
