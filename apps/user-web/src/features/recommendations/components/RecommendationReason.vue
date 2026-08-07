<script setup lang="ts">
import type { ExplanationEntry } from "@/features/recommendations/types";

/**
 * A single explanation group rendered as plain text.
 *
 * The backend supplies `display_text` already localised and already stripped of
 * every confidence value; this component only lists it.
 */
defineProps<{
  title: string;
  entries: ExplanationEntry[];
  hint?: string;
  tone?: "strength" | "preference" | "topic";
}>();
</script>

<template>
  <section
    v-if="entries.length"
    :class="['recommendation-reason', tone ?? 'strength']"
  >
    <h4>{{ title }}</h4>
    <ul>
      <li
        v-for="entry in entries"
        :key="entry.explanation_code"
      >
        {{ entry.display_text }}
      </li>
    </ul>
    <p
      v-if="hint"
      class="hint"
    >
      {{ hint }}
    </p>
  </section>
</template>

<style scoped>
.recommendation-reason { display: flex; flex-direction: column; gap: 0.35rem; }
.recommendation-reason h4 { margin: 0; font-size: 0.9rem; font-weight: 600; }
.recommendation-reason ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.25rem; }
.recommendation-reason li { font-size: 0.9rem; line-height: 1.6; padding-left: 0.9rem; position: relative; }
.recommendation-reason li::before { content: "·"; position: absolute; left: 0.2rem; }
.recommendation-reason.strength li::before { color: #3f7d58; }
.recommendation-reason.preference li::before { color: #1f2933; }
.recommendation-reason.topic li::before { color: #7a5c1e; }
.hint { font-size: 0.8rem; opacity: 0.7; }
</style>
