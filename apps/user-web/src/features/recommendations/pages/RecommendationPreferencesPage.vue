<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";

import { recommendationsApi } from "@/features/recommendations/api";
import { criterionText } from "@/features/recommendations/composables/useRecommendations";
import type { RecommendationPreferences } from "@/features/recommendations/types";

const DELIVERY_FREQUENCIES = [
  { value: "daily", label: "每天一批" },
  { value: "weekly", label: "每周一批" },
  { value: "manual", label: "只在我主动获取时" }
];

const EXPLORATION_LEVELS = [
  { value: "conservative", label: "保守", hint: "尽量只推荐完全符合你条件的人。" },
  { value: "balanced", label: "均衡", hint: "以你的条件为主，偶尔加入少量新的可能。" },
  { value: "adventurous", label: "开放", hint: "在你允许的范围内，更多尝试不同类型的人选。" }
];

/** Criteria a member may allow the engine to relax. Required conditions stay untouched. */
const RELAXABLE_CRITERIA = [
  "age_range",
  "city_code",
  "region_code",
  "relocation_willingness",
  "church_tradition_codes",
  "marriage_faith_importance",
  "education_level_code",
  "daily_schedule_code",
  "leisure_interest_codes",
  "communication_preference_codes",
  "language_codes"
];

const route = useRoute();
const preferences = ref<RecommendationPreferences>();
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const notice = ref("");

const form = reactive({
  recommendations_paused: false,
  daily_received_limit: 5,
  delivery_frequency: "daily",
  extended_recommendations_enabled: false,
  relaxable_criteria: [] as string[],
  exploration_level: "balanced",
  feedback_personalization_enabled: true
});

const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const listPath = computed(() => `/${locale.value}/recommendations`);
const transparencyPath = computed(() => `/${locale.value}/account/recommendation-transparency`);
const maximumDaily = computed(() => preferences.value?.maximum_daily_received ?? 20);

const relaxableOptions = computed(() => {
  const extra = form.relaxable_criteria.filter((code) => !RELAXABLE_CRITERIA.includes(code));
  return [...RELAXABLE_CRITERIA, ...extra];
});

function applyPreferences(value: RecommendationPreferences) {
  preferences.value = value;
  form.recommendations_paused = value.settings.recommendations_paused;
  form.daily_received_limit = value.settings.daily_received_limit ?? 5;
  form.delivery_frequency = value.settings.delivery_frequency;
  form.extended_recommendations_enabled = value.settings.extended_recommendations_enabled;
  form.relaxable_criteria = [...value.settings.relaxable_criteria];
  form.exploration_level = value.tuning.exploration_level;
  form.feedback_personalization_enabled = value.tuning.feedback_personalization_enabled;
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    applyPreferences(await recommendationsApi.preferences());
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "推荐设置加载失败";
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  error.value = "";
  notice.value = "";
  try {
    await recommendationsApi.savePreferences({
      recommendations_paused: form.recommendations_paused,
      daily_received_limit: Number(form.daily_received_limit),
      delivery_frequency: form.delivery_frequency,
      extended_recommendations_enabled: form.extended_recommendations_enabled,
      relaxable_criteria: [...form.relaxable_criteria]
    });
    await recommendationsApi.saveTuning({
      exploration_level: form.exploration_level,
      feedback_personalization_enabled: form.feedback_personalization_enabled
    });
    notice.value = "推荐设置已保存，将从下一批推荐开始生效。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "推荐设置保存失败";
  } finally {
    saving.value = false;
  }
}

async function resetTuning() {
  saving.value = true;
  error.value = "";
  notice.value = "";
  try {
    const result = await recommendationsApi.resetTuning();
    notice.value = `已清除 ${result.adjusted_feature_count} 项根据行为学习到的调整，恢复为平台默认设置。`;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "重置失败";
  } finally {
    saving.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="recommendation-preferences">
    <RouterLink :to="listPath">
      ← 返回今日推荐
    </RouterLink>
    <h1>推荐设置</h1>
    <p class="intro">
      这里的设置只影响你自己收到的推荐数量、节奏和范围，不会改变别人是否看到你，
      也不会绕过你在婚恋档案中标记为必须满足的条件。
    </p>

    <p
      v-if="error"
      class="alert error"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      class="alert notice"
      role="status"
    >
      {{ notice }}
    </p>
    <p v-if="loading">
      正在加载推荐设置…
    </p>

    <form
      class="panel"
      @submit.prevent="save"
    >
      <label class="inline">
        <input
          v-model="form.recommendations_paused"
          type="checkbox"
        >
        暂停接收推荐
      </label>
      <p class="hint">
        暂停后不会生成新的批次，你的档案也不会出现在他人的新推荐中。随时可以恢复。
      </p>

      <div class="field">
        <label for="daily-limit">每天最多接收</label>
        <input
          id="daily-limit"
          v-model.number="form.daily_received_limit"
          type="number"
          min="0"
          :max="maximumDaily"
        >
        <p class="hint">
          范围 0 - {{ maximumDaily }} 位。设置为 0 表示不再接收新的推荐。
        </p>
      </div>

      <div class="field">
        <label for="delivery-frequency">推荐频率</label>
        <select
          id="delivery-frequency"
          v-model="form.delivery_frequency"
        >
          <option
            v-for="option in DELIVERY_FREQUENCIES"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
      </div>

      <label class="inline">
        <input
          v-model="form.extended_recommendations_enabled"
          type="checkbox"
        >
        接收扩展推荐（在我允许放宽的条件内）
      </label>
      <p class="hint">
        开启后，当完全符合条件的人选不足时，系统可以在下方勾选的条件上适度放宽，并在推荐中明确标注。
      </p>

      <fieldset class="field">
        <legend>允许放宽的条件</legend>
        <label
          v-for="code in relaxableOptions"
          :key="code"
          class="inline"
        >
          <input
            v-model="form.relaxable_criteria"
            type="checkbox"
            :value="code"
          >
          {{ criterionText(code) }}
        </label>
        <p class="hint">
          未勾选的条件永远不会被系统放宽。安全相关的限制不受此设置影响。
        </p>
      </fieldset>

      <fieldset class="field">
        <legend>探索程度</legend>
        <label
          v-for="option in EXPLORATION_LEVELS"
          :key="option.value"
          class="inline"
        >
          <input
            v-model="form.exploration_level"
            type="radio"
            name="exploration-level"
            :value="option.value"
          >
          {{ option.label }} — {{ option.hint }}
        </label>
      </fieldset>

      <label class="inline">
        <input
          v-model="form.feedback_personalization_enabled"
          type="checkbox"
        >
        允许根据我的浏览与反馈调整推荐
      </label>
      <p class="hint">
        关闭后，推荐只使用你明确填写的条件。已经学习到的调整可以用下方按钮清除。
      </p>

      <div class="actions">
        <button
          type="submit"
          class="primary"
          :disabled="saving"
        >
          {{ saving ? "保存中…" : "保存设置" }}
        </button>
        <button
          type="button"
          :disabled="saving"
          @click="resetTuning"
        >
          重置个性化调整
        </button>
      </div>
      <p
        v-if="preferences"
        class="hint"
      >
        当前已根据行为调整 {{ preferences.tuning.adjusted_feature_count }} 项。
      </p>
    </form>

    <RouterLink :to="transparencyPath">
      查看推荐使用了哪些资料
    </RouterLink>
  </section>
</template>

<style scoped>
.recommendation-preferences { display: flex; flex-direction: column; gap: 1rem; padding: 2rem 0; }
.recommendation-preferences h1 { margin: 0; font-size: 1.4rem; }
.intro { max-width: 62ch; line-height: 1.7; margin: 0; }
.alert { padding: 0.75rem 1rem; border-radius: 0.5rem; margin: 0; }
.alert.error { background: #fdecea; color: #8a1c12; }
.alert.notice { background: #eaf6ec; color: #1c5a2a; }
.panel { display: flex; flex-direction: column; gap: 0.85rem; padding: 1.5rem; border: 1px solid rgba(0, 0, 0, 0.1); border-radius: 0.75rem; }
.field { display: flex; flex-direction: column; gap: 0.35rem; border: none; padding: 0; margin: 0; }
.field legend { font-weight: 600; padding: 0 0 0.35rem; }
.field label { font-weight: 600; }
.inline { display: flex; align-items: center; gap: 0.5rem; font-weight: 500; }
.hint { font-size: 0.85rem; opacity: 0.75; line-height: 1.6; margin: 0; }
.actions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.actions button { padding: 0.5rem 1.2rem; border-radius: 0.5rem; border: 1px solid rgba(0, 0, 0, 0.15); background: transparent; cursor: pointer; }
.actions button.primary { background: #1f2933; color: #fff; border-color: #1f2933; }
.actions button:disabled { opacity: 0.45; cursor: not-allowed; }
input[type="number"], select { padding: 0.4rem 0.6rem; border-radius: 0.5rem; border: 1px solid rgba(0, 0, 0, 0.2); max-width: 16rem; }
</style>
