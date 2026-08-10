<script setup lang="ts">
import type { ExplanationEntry } from "@/features/recommendations/types";

/**
 * What the platform does not know yet.
 *
 * A gap is stated as missing information, never as a shortcoming of either
 * member, and never guessed at.
 */
defineProps<{
  gaps: ExplanationEntry[];
}>();
</script>

<template>
  <section
    v-if="gaps.length"
    class="information-gap"
  >
    <h4>尚未确认的信息</h4>
    <ul>
      <li
        v-for="gap in gaps"
        :key="gap.explanation_code"
      >
        {{ gap.display_text }}
      </li>
    </ul>
    <p class="hint">
      未填写的内容不会被推测，也不会被当作缺点。可以在进一步了解时自行确认。
    </p>
  </section>
</template>

<style scoped>
.information-gap { display: flex; flex-direction: column; gap: 0.35rem; padding: 0.6rem 0.8rem; border-radius: 0.5rem; background: rgba(0, 0, 0, 0.04); }
.information-gap h4 { margin: 0; font-size: 0.9rem; font-weight: 600; }
.information-gap ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.25rem; }
.information-gap li { font-size: 0.9rem; line-height: 1.6; }
.hint { font-size: 0.8rem; opacity: 0.7; line-height: 1.6; }
</style>
