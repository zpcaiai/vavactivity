<script setup lang="ts">
import { computed } from "vue";

import { criterionText } from "@/features/recommendations/composables/useRecommendations";
import type { RecommendationTransparencyData } from "@/features/recommendations/types";

const FEATURE_GROUP_LABELS: Record<string, string> = {
  faith_and_values: "信仰与价值观",
  location_and_relocation: "所在地与搬迁意愿",
  relationship_intent: "关系目标",
  family_and_parenting: "家庭与生育",
  lifestyle: "生活方式",
  interests: "兴趣爱好",
  communication: "沟通方式",
  language: "语言",
  education_and_work: "教育与工作",
  profile_readiness: "档案完整度"
};

const NEVER_USED_LABELS: Record<string, string> = {
  photo_attractiveness: "照片外貌评分",
  ai_conversations: "你与 AI 辅导的对话内容",
  counseling_records: "真人辅导记录",
  payment_history: "消费与付款记录",
  health_or_personality_inference: "健康状况或性格推断"
};

const HOW_TO_ADJUST_LABELS: Record<string, string> = {
  update_partner_preferences: "更新婚恋档案中的择偶条件",
  change_relaxable_criteria: "修改允许系统放宽的条件",
  change_exploration_level: "调整推荐的探索程度",
  disable_behavioural_personalization: "关闭基于浏览行为的个性化",
  pause_recommendations: "暂停接收推荐"
};

const props = defineProps<{
  transparency: RecommendationTransparencyData;
}>();

const categories = computed(() =>
  props.transparency.data_categories_used.map(
    (code) => FEATURE_GROUP_LABELS[code] ?? code
  )
);

const statedFeatures = computed(() =>
  props.transparency.features.filter((feature) => feature.source === "your_stated_preference")
);

const defaultFeatures = computed(() =>
  props.transparency.features.filter((feature) => feature.source !== "your_stated_preference")
);

function groupLabel(code: string) {
  return FEATURE_GROUP_LABELS[code] ?? code;
}
</script>

<template>
  <div class="transparency">
    <section class="block">
      <h2>推荐使用了哪些资料类别</h2>
      <ul class="tags">
        <li
          v-for="category in categories"
          :key="category"
        >
          {{ category }}
        </li>
      </ul>
      <p class="hint">
        推荐只使用你和对方已批准展示的档案资料，不使用照片外貌、聊天内容或消费记录。
      </p>
    </section>

    <section class="block">
      <h2>来自你自己填写的条件</h2>
      <ul
        v-if="statedFeatures.length"
        class="plain"
      >
        <li
          v-for="feature in statedFeatures"
          :key="feature.feature_code"
        >
          {{ groupLabel(feature.feature_group) }} · {{ feature.feature_code }}
          <span class="tag">你设置的条件</span>
          <span
            v-if="feature.your_information_available === false"
            class="tag warn"
          >你的档案暂无此项资料</span>
        </li>
      </ul>
      <p
        v-else
        class="hint"
      >
        你还没有设置任何择偶条件，目前全部使用平台默认权重。
      </p>
    </section>

    <section class="block">
      <h2>使用平台默认设置的部分</h2>
      <ul class="plain">
        <li
          v-for="feature in defaultFeatures"
          :key="feature.feature_code"
        >
          {{ groupLabel(feature.feature_group) }} · {{ feature.feature_code }}
          <span class="tag muted">平台默认</span>
          <span
            v-if="!feature.user_configurable"
            class="tag muted"
          >不可自行调整</span>
        </li>
      </ul>
      <p class="hint">
        平台默认设置对所有会员一致，你填写的条件会优先于默认设置。
      </p>
    </section>

    <section
      v-if="transparency.hard_constraints_from_you.length"
      class="block"
    >
      <h2>你要求必须满足的条件</h2>
      <ul class="tags">
        <li
          v-for="code in transparency.hard_constraints_from_you"
          :key="code"
        >
          {{ criterionText(code) }}
        </li>
      </ul>
      <p class="hint">
        这些条件不会被系统放宽，除非你在推荐设置中明确允许。
      </p>
    </section>

    <section class="block">
      <h2>永远不会被使用的资料</h2>
      <ul class="plain">
        <li
          v-for="code in transparency.never_used"
          :key="code"
        >
          {{ NEVER_USED_LABELS[code] ?? code }}
        </li>
      </ul>
    </section>

    <section class="block">
      <h2>基于浏览行为的个性化</h2>
      <p>
        当前状态：{{ transparency.behavioural_personalization_enabled ? "已开启" : "已关闭" }}。
        开启后，你的浏览与“不合适”反馈会用于调整你自己的推荐顺序；关闭后只使用你填写的条件。
      </p>
    </section>

    <section class="block">
      <h2>如何调整</h2>
      <ul class="plain">
        <li
          v-for="code in transparency.how_to_adjust"
          :key="code"
        >
          {{ HOW_TO_ADJUST_LABELS[code] ?? code }}
        </li>
      </ul>
      <slot name="actions" />
    </section>
  </div>
</template>

<style scoped>
.transparency { display: flex; flex-direction: column; gap: 1.25rem; }
.block { display: flex; flex-direction: column; gap: 0.4rem; padding: 1rem 1.25rem; border: 1px solid rgba(0, 0, 0, 0.1); border-radius: 0.75rem; }
.block h2 { margin: 0; font-size: 1rem; }
.tags { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 0.4rem; }
.tags li { font-size: 0.8rem; padding: 0.1rem 0.55rem; border-radius: 999px; background: rgba(0, 0, 0, 0.06); }
.plain { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.9rem; line-height: 1.6; }
.tag { font-size: 0.72rem; padding: 0.05rem 0.45rem; border-radius: 999px; background: rgba(63, 125, 88, 0.15); margin-left: 0.35rem; }
.tag.muted { background: rgba(0, 0, 0, 0.06); }
.tag.warn { background: rgba(200, 160, 74, 0.2); }
.hint { font-size: 0.82rem; opacity: 0.72; line-height: 1.6; margin: 0; }
</style>
