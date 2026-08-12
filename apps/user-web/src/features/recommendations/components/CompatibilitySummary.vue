<script setup lang="ts">
import RecommendationReason from "@/features/recommendations/components/RecommendationReason.vue";
import type { RecommendationExplanation } from "@/features/recommendations/types";

/**
 * The textual reason this member appears in your list.
 *
 * There is no percentage, no score and no ranking number here by design: the
 * API never returns one and this component never derives one. Nothing shown
 * describes what the other member thinks of you.
 */
defineProps<{
  explanation: RecommendationExplanation;
  compact?: boolean;
}>();
</script>

<template>
  <section class="compatibility-summary">
    <p
      v-if="explanation.summary"
      class="summary"
    >
      {{ explanation.summary }}
    </p>

    <RecommendationReason
      title="你们的共同点"
      tone="strength"
      :entries="explanation.mutual_strengths"
    />

    <template v-if="!compact">
      <RecommendationReason
        title="与你设置的择偶条件相关"
        tone="preference"
        :entries="explanation.relevant_preferences"
        hint="这里只显示你自己填写的条件，不会显示对方的择偶条件。"
      />
      <RecommendationReason
        title="可以聊聊的话题"
        tone="topic"
        :entries="explanation.topics_to_explore"
      />
    </template>

    <p
      v-if="explanation.caveat"
      class="caveat"
    >
      {{ explanation.caveat }}
    </p>
    <p class="boundary">
      平台不提供匹配分数或百分比，也不会展示对方对你的评价。是否继续了解，由你自己决定。
    </p>
  </section>
</template>

<style scoped>
.compatibility-summary { display: flex; flex-direction: column; gap: 0.75rem; }
.summary { line-height: 1.7; margin: 0; }
.caveat { font-size: 0.85rem; line-height: 1.6; padding: 0.6rem 0.8rem; border-left: 3px solid var(--vav-color-accent); background: rgba(200, 160, 74, 0.08); }
.boundary { font-size: 0.8rem; opacity: 0.7; line-height: 1.6; }
</style>
