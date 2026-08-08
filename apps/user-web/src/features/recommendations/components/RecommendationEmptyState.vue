<script setup lang="ts">
import { computed } from "vue";

import { criterionText } from "@/features/recommendations/composables/useRecommendations";
import type { RecommendationEmptyStateData } from "@/features/recommendations/types";

/** zh-CN copy for the alternatives the backend offers when nothing matched. */
const ACTION_LABELS: Record<string, string> = {
  review_most_restrictive_criteria: "检视最严格的择偶条件",
  enable_allowed_relaxations: "允许系统放宽部分条件",
  wait_for_new_profiles: "等待新的档案通过审核",
  browse_activities_or_courses: "先参加活动或课程",
  pause_recommendations: "暂停接收推荐"
};

const COLD_START_LABELS: Record<string, string> = {
  new_account: "账户刚建立不久",
  new_profile: "档案刚通过审核",
  sparse_preferences: "填写的择偶条件较少",
  sparse_region: "所在地区可推荐的档案还不多",
  no_interaction_history: "还没有足够的互动记录"
};

const GUIDANCE_LABELS: Record<string, string> = {
  add_three_to_five_important_criteria: "先填写 3-5 项你最看重的条件",
  mark_criteria_required_important_or_no_preference: "把每项条件标记为必须满足、比较看重或无所谓",
  review_relaxable_criteria: "检查哪些条件允许系统放宽"
};

const props = defineProps<{
  emptyState: RecommendationEmptyStateData | null;
  /** Locale-prefixed paths so the member can act immediately. */
  preferencesPath: string;
  activitiesPath: string;
  datingPreferencesPath?: string;
}>();

const emit = defineEmits<{ (event: "pause"): void }>();

const actions = computed(() =>
  (props.emptyState?.available_actions ?? []).map((code) => ({
    code,
    label: ACTION_LABELS[code] ?? code
  }))
);

const criteria = computed(() => props.emptyState?.most_restrictive_criteria ?? []);

const coldStartTypes = computed(() =>
  (props.emptyState?.cold_start?.types ?? []).map((code) => COLD_START_LABELS[code] ?? code)
);

const guidance = computed(() =>
  (props.emptyState?.cold_start?.guidance_codes ?? []).map((code) => GUIDANCE_LABELS[code] ?? code)
);
</script>

<template>
  <section class="recommendation-empty">
    <h2>今天没有符合你条件的推荐</h2>
    <p class="intro">
      系统不会为了凑数而降低你设定的条件。以下说明只统计条件的排除次数，不涉及任何具体会员。
    </p>

    <div
      v-if="coldStartTypes.length"
      class="block"
    >
      <h3>可能的原因</h3>
      <ul class="tags">
        <li
          v-for="type in coldStartTypes"
          :key="type"
        >
          {{ type }}
        </li>
      </ul>
      <ul
        v-if="guidance.length"
        class="plain"
      >
        <li
          v-for="tip in guidance"
          :key="tip"
        >
          {{ tip }}
        </li>
      </ul>
    </div>

    <div
      v-if="criteria.length"
      class="block"
    >
      <h3>排除人数最多的条件</h3>
      <ul class="plain">
        <li
          v-for="criterion in criteria"
          :key="criterion.criterion_code"
        >
          {{ criterionText(criterion.criterion_code) }} · 排除 {{ criterion.excluded_count }} 位候选
        </li>
      </ul>
      <p class="hint">
        这里只显示条件代码与数量，不会显示任何会员的身份或资料。
      </p>
    </div>

    <div
      v-if="actions.length"
      class="block"
    >
      <h3>你可以</h3>
      <ul class="plain">
        <li
          v-for="action in actions"
          :key="action.code"
        >
          {{ action.label }}
        </li>
      </ul>
    </div>

    <div class="links">
      <RouterLink :to="preferencesPath">
        调整推荐设置
      </RouterLink>
      <RouterLink
        v-if="datingPreferencesPath"
        :to="datingPreferencesPath"
      >
        修改择偶条件
      </RouterLink>
      <RouterLink :to="activitiesPath">
        去看看活动
      </RouterLink>
      <button
        type="button"
        class="quiet"
        @click="emit('pause')"
      >
        暂停接收推荐
      </button>
    </div>
  </section>
</template>

<style scoped>
.recommendation-empty { display: flex; flex-direction: column; gap: 1rem; padding: 1.5rem; border: 1px dashed rgba(0, 0, 0, 0.25); border-radius: 0.75rem; }
.recommendation-empty h2 { margin: 0; font-size: 1.15rem; }
.recommendation-empty h3 { margin: 0 0 0.35rem; font-size: 0.95rem; }
.intro { margin: 0; line-height: 1.7; max-width: 62ch; }
.block { display: flex; flex-direction: column; gap: 0.35rem; }
.tags { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 0.4rem; }
.tags li { font-size: 0.8rem; padding: 0.1rem 0.55rem; border-radius: 999px; background: rgba(0, 0, 0, 0.06); }
.plain { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.9rem; line-height: 1.6; }
.hint { font-size: 0.8rem; opacity: 0.7; margin: 0; }
.links { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; }
.links button.quiet { padding: 0.35rem 0.9rem; border-radius: 0.5rem; border: 1px dashed rgba(0, 0, 0, 0.25); background: transparent; cursor: pointer; }
</style>
