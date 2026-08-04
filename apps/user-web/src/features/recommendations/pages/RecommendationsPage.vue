<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import {
  EXPLORATION_LEVELS,
  SKIP_REASONS,
  recommendationsApi,
  type HistoryEntry,
  type RecommendationBatch,
  type RecommendationItem,
  type RecommendationPreferences,
  type Transparency
} from "@/features/recommendations/api";

type TabKey = "today" | "settings" | "history" | "transparency";

const TABS: { key: TabKey; label: string }[] = [
  { key: "today", label: "今日推荐" },
  { key: "settings", label: "推荐设置" },
  { key: "history", label: "推荐记录" },
  { key: "transparency", label: "推荐说明" }
];

const route = useRoute();
const tab = ref<TabKey>("today");
const busy = ref(false);
const error = ref("");
const notice = ref("");

const batch = ref<RecommendationBatch>();
const preferences = ref<RecommendationPreferences>();
const transparency = ref<Transparency>();
const history = ref<HistoryEntry[]>([]);
const historyTotal = ref(0);
const expanded = ref<string | null>(null);
const skipTarget = ref<RecommendationItem | null>(null);
const skipReason = ref("prefer_not_to_say");

/** Cards only count as seen once they have been visible long enough. */
const visibleSince = new Map<string, number>();
const reported = new Set<string>();
let observer: IntersectionObserver | undefined;

const items = computed(() => batch.value?.items ?? []);
const guidance = computed(() => batch.value?.guidance ?? null);
const paused = computed(() => preferences.value?.recommendations_paused === true);

function summaryLine(item: RecommendationItem): string {
  const summary = item.profile_summary ?? {};
  const parts = [summary.age_bucket, summary.city_code, summary.relationship_intent].filter(Boolean);
  return parts.join(" · ") || "资料正在完善中";
}

async function loadBatch() {
  batch.value = await recommendationsApi.current();
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    const [current, prefs] = await Promise.all([
      recommendationsApi.current(),
      recommendationsApi.preferences()
    ]);
    batch.value = current;
    preferences.value = prefs;
  } catch (loadError) {
    error.value = (loadError as Error).message;
  } finally {
    busy.value = false;
  }
}

async function generate() {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await recommendationsApi.generate();
    await loadBatch();
    notice.value = "已为你生成新的推荐。";
  } catch (generateError) {
    error.value = (generateError as Error).message;
  } finally {
    busy.value = false;
  }
}

function observe(element: Element | null, itemId: string) {
  if (!element || !observer) return;
  (element as HTMLElement).dataset.itemId = itemId;
  observer.observe(element);
}

async function reportVisible(itemId: string, durationMs: number) {
  if (reported.has(itemId)) return;
  reported.add(itemId);
  try {
    await recommendationsApi.recordExposure(itemId, "card_visible", durationMs);
  } catch {
    // An exposure that fails to record is never allowed to break the page.
    reported.delete(itemId);
  }
}

async function openDetail(item: RecommendationItem) {
  expanded.value = expanded.value === item.recommendation_item_id ? null : item.recommendation_item_id;
  if (expanded.value) {
    try {
      await recommendationsApi.recordExposure(item.recommendation_item_id, "profile_opened");
    } catch {
      /* viewing still works even if the signal is lost */
    }
  }
}

async function sendFeedback(item: RecommendationItem, feedbackType: string, reasonCode?: string) {
  busy.value = true;
  error.value = "";
  try {
    await recommendationsApi.sendFeedback({
      recommended_user_id: item.recommended_user_id,
      feedback_type: feedbackType,
      reason_code: reasonCode ?? null,
      recommendation_item_id: item.recommendation_item_id
    });
    notice.value =
      feedbackType === "skipped"
        ? "已记录。你之后仍可能再次看到相似的人。"
        : "已记录你的反馈。";
    skipTarget.value = null;
    await loadBatch();
  } catch (feedbackError) {
    error.value = (feedbackError as Error).message;
  } finally {
    busy.value = false;
  }
}

async function savePreferences(patch: Partial<RecommendationPreferences>) {
  busy.value = true;
  error.value = "";
  try {
    preferences.value = await recommendationsApi.savePreferences(patch);
    notice.value = "推荐设置已更新。";
  } catch (saveError) {
    error.value = (saveError as Error).message;
  } finally {
    busy.value = false;
  }
}

async function resetPreferences() {
  busy.value = true;
  try {
    await recommendationsApi.resetPreferences();
    preferences.value = await recommendationsApi.preferences();
    notice.value = "已清除所有从反馈中学到的调整。";
  } catch (resetError) {
    error.value = (resetError as Error).message;
  } finally {
    busy.value = false;
  }
}

async function openTab(key: TabKey) {
  tab.value = key;
  try {
    if (key === "history" && history.value.length === 0) {
      const page = await recommendationsApi.history();
      history.value = page.items;
      historyTotal.value = page.total;
    }
    if (key === "transparency" && !transparency.value) {
      transparency.value = await recommendationsApi.transparency();
    }
  } catch (tabError) {
    error.value = (tabError as Error).message;
  }
}

onMounted(() => {
  if (typeof IntersectionObserver !== "undefined") {
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const itemId = (entry.target as HTMLElement).dataset.itemId;
          if (!itemId) continue;
          if (entry.isIntersecting) {
            visibleSince.set(itemId, Date.now());
          } else {
            const start = visibleSince.get(itemId);
            visibleSince.delete(itemId);
            if (start) {
              const duration = Date.now() - start;
              if (duration >= 1000) void reportVisible(itemId, duration);
            }
          }
        }
      },
      { threshold: 0.6 }
    );
  }
  void load();
});

onBeforeUnmount(() => {
  observer?.disconnect();
});

const localePrefix = computed(() => `/${String(route.params.locale ?? "zh-CN")}`);
</script>

<template>
  <section class="recommendations">
    <header class="recommendations__header">
      <h1>推荐</h1>
      <p class="recommendations__lead">
        推荐只是一个认识的机会，不代表平台对适配结果的保证。
      </p>
      <nav class="recommendations__tabs">
        <button
          v-for="entry in TABS"
          :key="entry.key"
          type="button"
          :class="{ 'is-active': tab === entry.key }"
          @click="openTab(entry.key)"
        >
          {{ entry.label }}
        </button>
      </nav>
    </header>

    <p
      v-if="error"
      class="recommendations__error"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      class="recommendations__notice"
    >
      {{ notice }}
    </p>

    <div
      v-if="tab === 'today'"
      class="recommendations__panel"
    >
      <p
        v-if="paused"
        class="recommendations__paused"
      >
        你已暂停推荐。可以在「推荐设置」中随时恢复。
      </p>
      <div
        v-else
        class="recommendations__actions"
      >
        <button
          type="button"
          :disabled="busy"
          @click="generate"
        >
          获取今日推荐
        </button>
      </div>

      <p v-if="busy && items.length === 0">
        正在加载…
      </p>

      <ol
        v-if="items.length"
        class="recommendations__list"
      >
        <li
          v-for="item in items"
          :key="item.recommendation_item_id"
          :ref="(element) => observe(element as Element | null, item.recommendation_item_id)"
          class="card"
        >
          <div class="card__head">
            <span class="card__rank">#{{ item.rank_position }}</span>
            <span
              v-if="item.is_exploration_slot"
              class="card__badge"
            >探索位</span>
          </div>
          <p class="card__summary">
            {{ summaryLine(item) }}
          </p>
          <p class="card__explanation">
            {{ item.explanation.summary }}
          </p>

          <ul
            v-if="item.explanation.mutual_strengths.length"
            class="card__points"
          >
            <li
              v-for="point in item.explanation.mutual_strengths"
              :key="point.explanation_code"
            >
              {{ point.display_text }}
            </li>
          </ul>

          <div
            v-if="expanded === item.recommendation_item_id"
            class="card__detail"
          >
            <section v-if="item.explanation.relevant_preferences.length">
              <h3>符合你标记的条件</h3>
              <ul>
                <li
                  v-for="point in item.explanation.relevant_preferences"
                  :key="point.explanation_code"
                >
                  {{ point.display_text }}
                </li>
              </ul>
            </section>
            <section v-if="item.explanation.topics_to_explore.length">
              <h3>可以聊聊的话题</h3>
              <ul>
                <li
                  v-for="point in item.explanation.topics_to_explore"
                  :key="point.explanation_code"
                >
                  {{ point.display_text }}
                </li>
              </ul>
            </section>
            <section v-if="item.explanation.information_gaps.length">
              <h3>还不清楚的部分</h3>
              <ul>
                <li
                  v-for="point in item.explanation.information_gaps"
                  :key="point.explanation_code"
                >
                  {{ point.display_text }}
                </li>
              </ul>
            </section>
            <p
              v-if="item.relaxation_applied.length"
              class="card__relaxation"
            >
              此推荐放宽了你允许放宽的条件：{{ item.relaxation_applied.join("、") }}
            </p>
            <p class="card__caveat">
              {{ item.explanation.caveat }}
            </p>
          </div>

          <div class="card__actions">
            <button
              type="button"
              @click="openDetail(item)"
            >
              {{ expanded === item.recommendation_item_id ? "收起" : "查看更多" }}
            </button>
            <button
              type="button"
              :disabled="busy"
              @click="sendFeedback(item, 'liked')"
            >
              有兴趣
            </button>
            <button
              type="button"
              :disabled="busy"
              @click="skipTarget = item"
            >
              暂不考虑
            </button>
          </div>

          <div
            v-if="skipTarget?.recommendation_item_id === item.recommendation_item_id"
            class="card__skip"
          >
            <label>
              可以告诉我们原因吗？（可以不说明）
              <select v-model="skipReason">
                <option
                  v-for="reason in SKIP_REASONS"
                  :key="reason.code"
                  :value="reason.code"
                >
                  {{ reason.label }}
                </option>
              </select>
            </label>
            <button
              type="button"
              :disabled="busy"
              @click="sendFeedback(item, 'skipped', skipReason)"
            >
              确认
            </button>
            <button
              type="button"
              @click="skipTarget = null"
            >
              取消
            </button>
          </div>
        </li>
      </ol>

      <div
        v-else-if="guidance"
        class="recommendations__empty"
      >
        <p>{{ guidance.message }}</p>
        <ul v-if="guidance.largest_reductions.length">
          <li
            v-for="entry in guidance.largest_reductions"
            :key="entry.criterion_code"
          >
            条件「{{ entry.criterion_code }}」排除了 {{ entry.excluded_candidates }} 位候选人
          </li>
        </ul>
        <h3>你可以</h3>
        <ul>
          <li
            v-for="option in guidance.options"
            :key="option"
          >
            {{ option }}
          </li>
        </ul>
        <h3>平台不会做的事</h3>
        <ul>
          <li
            v-for="never in guidance.never_done"
            :key="never"
          >
            {{ never }}
          </li>
        </ul>
        <p>
          <a :href="`${localePrefix}/account/dating-profile/preferences`">调整择偶条件</a>
        </p>
      </div>
    </div>

    <div
      v-else-if="tab === 'settings' && preferences"
      class="recommendations__panel"
    >
      <label class="field">
        探索强度
        <select
          :value="preferences.exploration_level"
          @change="savePreferences({ exploration_level: ($event.target as HTMLSelectElement).value })"
        >
          <option
            v-for="level in EXPLORATION_LEVELS"
            :key="level.code"
            :value="level.code"
          >
            {{ level.label }} — {{ level.description }}
          </option>
        </select>
      </label>

      <label class="field">
        每日接收上限（最多 {{ preferences.maximum_daily_received_limit }}）
        <input
          type="number"
          min="1"
          :max="preferences.maximum_daily_received_limit"
          :value="preferences.daily_received_limit"
          @change="savePreferences({ daily_received_limit: Number(($event.target as HTMLInputElement).value) })"
        >
      </label>

      <label class="field field--check">
        <input
          type="checkbox"
          :checked="preferences.feedback_personalization_enabled"
          @change="savePreferences({ feedback_personalization_enabled: ($event.target as HTMLInputElement).checked })"
        >
        允许根据我的反馈微调推荐
      </label>

      <label class="field field--check">
        <input
          type="checkbox"
          :checked="preferences.allow_relaxed_recommendations"
          @change="savePreferences({ allow_relaxed_recommendations: ($event.target as HTMLInputElement).checked })"
        >
        候选不足时，允许放宽我标记为「可放宽」的条件
      </label>

      <label class="field field--check">
        <input
          type="checkbox"
          :checked="preferences.recommendations_paused"
          @change="savePreferences({ recommendations_paused: ($event.target as HTMLInputElement).checked })"
        >
        暂停推荐
      </label>

      <button
        type="button"
        :disabled="busy"
        @click="resetPreferences"
      >
        清除所有从反馈中学到的调整
      </button>

      <section class="recommendations__limits">
        <h3>任何设置都不会</h3>
        <ul>
          <li
            v-for="entry in preferences.cannot_configure"
            :key="entry"
          >
            {{ entry }}
          </li>
        </ul>
      </section>
    </div>

    <div
      v-else-if="tab === 'history'"
      class="recommendations__panel"
    >
      <p>共 {{ historyTotal }} 条推荐记录。</p>
      <ul class="recommendations__history">
        <li
          v-for="entry in history"
          :key="entry.id"
        >
          第 {{ entry.rank_position }} 位 · {{ entry.status }}
          <span v-if="entry.is_exploration_slot">（探索位）</span>
        </li>
      </ul>
    </div>

    <div
      v-else-if="tab === 'transparency' && transparency"
      class="recommendations__panel"
    >
      <section>
        <h3>用到了哪些信息</h3>
        <ul>
          <li
            v-for="entry in transparency.data_categories_used"
            :key="entry"
          >
            {{ entry }}
          </li>
        </ul>
      </section>
      <section>
        <h3>你明确设置的条件</h3>
        <ul>
          <li
            v-for="entry in transparency.your_explicit_preferences"
            :key="entry"
          >
            {{ entry }}
          </li>
        </ul>
      </section>
      <section>
        <h3>永远不会被使用的信息</h3>
        <ul>
          <li
            v-for="entry in transparency.never_used"
            :key="entry"
          >
            {{ entry }}
          </li>
        </ul>
      </section>
      <section>
        <h3>你无法查看的内容</h3>
        <ul>
          <li
            v-for="entry in transparency.cannot_view"
            :key="entry"
          >
            {{ entry }}
          </li>
        </ul>
      </section>
      <section v-if="transparency.preference_guidance.needed">
        <h3>让推荐更贴近你</h3>
        <ul>
          <li
            v-for="entry in transparency.preference_guidance.messages"
            :key="entry"
          >
            {{ entry }}
          </li>
        </ul>
      </section>
    </div>
  </section>
</template>

<style scoped>
.recommendations {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 52rem;
  margin: 0 auto;
  padding: 1.5rem 1rem 3rem;
}

.recommendations__lead {
  color: #5b6472;
  font-size: 0.95rem;
}

.recommendations__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.recommendations__tabs button {
  border: 1px solid #d7dce4;
  background: #fff;
  border-radius: 999px;
  padding: 0.35rem 0.9rem;
  cursor: pointer;
}

.recommendations__tabs button.is-active {
  background: #1f3d7a;
  border-color: #1f3d7a;
  color: #fff;
}

.recommendations__error {
  color: #a4262c;
}

.recommendations__notice {
  color: #1f6f43;
}

.recommendations__list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  list-style: none;
  padding: 0;
}

.card {
  border: 1px solid #e2e6ec;
  border-radius: 0.75rem;
  padding: 1rem;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.card__head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.card__rank {
  font-weight: 600;
  color: #1f3d7a;
}

.card__badge {
  font-size: 0.75rem;
  background: #eef3ff;
  color: #1f3d7a;
  border-radius: 999px;
  padding: 0.1rem 0.5rem;
}

.card__points,
.card__detail ul {
  margin: 0;
  padding-left: 1.1rem;
  color: #3d4552;
}

.card__caveat,
.card__relaxation {
  font-size: 0.85rem;
  color: #6b7280;
}

.card__actions,
.card__skip {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  margin-bottom: 0.9rem;
}

.field--check {
  flex-direction: row;
  align-items: center;
  gap: 0.5rem;
}

.recommendations__empty {
  border: 1px dashed #d7dce4;
  border-radius: 0.75rem;
  padding: 1rem;
}
</style>
