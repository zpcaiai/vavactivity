<script setup lang="ts">
import { computed } from "vue";

import { criterionText } from "@/features/recommendations/composables/useRecommendations";

const props = defineProps<{
  notices: string[];
  preferencesPath?: string;
}>();

const noticeTexts = computed(() =>
  props.notices.map((code) => ({ code, text: criterionText(code) }))
);
</script>

<template>
  <section
    v-if="notices.length"
    class="preference-relaxation"
  >
    <h4>这条推荐放宽了你允许放宽的条件</h4>
    <ul>
      <li
        v-for="(notice, index) in noticeTexts"
        :key="`${notice.code}-${index}`"
      >
        {{ notice.text }}
      </li>
    </ul>
    <p class="hint">
      只有你在推荐设置中标记为“可放宽”的条件才会被放宽；标记为必须满足的条件永远不会被跳过。
    </p>
    <RouterLink
      v-if="preferencesPath"
      :to="preferencesPath"
    >
      调整可放宽的条件
    </RouterLink>
  </section>
</template>

<style scoped>
.preference-relaxation { display: flex; flex-direction: column; gap: 0.35rem; padding: 0.6rem 0.8rem; border: 1px dashed rgba(0, 0, 0, 0.2); border-radius: 0.5rem; }
.preference-relaxation h4 { margin: 0; font-size: 0.9rem; font-weight: 600; }
.preference-relaxation ul { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 0.4rem; }
.preference-relaxation li { font-size: 0.8rem; padding: 0.1rem 0.55rem; border-radius: 999px; background: rgba(0, 0, 0, 0.06); }
.hint { font-size: 0.8rem; opacity: 0.7; line-height: 1.6; }
</style>
