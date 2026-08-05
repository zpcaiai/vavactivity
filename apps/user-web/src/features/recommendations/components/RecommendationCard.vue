<script setup lang="ts">
import { computed, ref } from "vue";

import CompatibilitySummary from "@/features/recommendations/components/CompatibilitySummary.vue";
import ExposureNotice from "@/features/recommendations/components/ExposureNotice.vue";
import InformationGap from "@/features/recommendations/components/InformationGap.vue";
import PreferenceRelaxationCard from "@/features/recommendations/components/PreferenceRelaxationCard.vue";
import type { RecommendationItem } from "@/features/recommendations/types";
import { matchmakingInteractionsApi } from "@/features/matchmaking-interactions/api";

/**
 * One recommendation, exactly as the backend froze it for this viewer.
 *
 * What is shown: approved display name, age display, city-level location,
 * primary photo placeholder, short introduction and the backend's own
 * explanation text.
 *
 * What is never shown: any compatibility percentage or score, the other
 * member's opinion of the viewer, their preference list, their contact details
 * or their exact birth date. None of these are returned by the API and none are
 * computed here.
 */
const props = defineProps<{
  item: RecommendationItem;
  detailPath?: string;
  preferencesPath?: string;
  /** Detail view shows the full explanation; the list card stays compact. */
  detailed?: boolean;
}>();

const emit = defineEmits<{
  (event: "open", itemId: string): void;
  (event: "not-relevant", itemId: string): void;
  (event: "interacted", itemId: string): void;
}>();

const acting = ref(false);
const interactionNotice = ref("");
const interactionError = ref("");

async function like() {
  if (!window.confirm("喜欢只会在双方都选择彼此后通知对方。确定表达兴趣吗？")) return;
  acting.value = true;
  interactionError.value = "";
  try {
    const result = await matchmakingInteractionsApi.like(props.item.recommendation_item_id);
    interactionNotice.value = result.outcome === "mutual_match"
      ? "你们已经双方互选，可以进入认识邀请。"
      : "已记录你的选择；单向喜欢不会通知对方。";
    emit("interacted", props.item.recommendation_item_id);
  } catch (cause) {
    interactionError.value = cause instanceof Error ? cause.message : "喜欢操作失败";
  } finally {
    acting.value = false;
  }
}

async function skip() {
  acting.value = true;
  interactionError.value = "";
  try {
    await matchmakingInteractionsApi.skip(props.item.recommendation_item_id, {
      skip_type: "not_now"
    });
    interactionNotice.value = "已暂时跳过；对方不会看到这个选择。";
    emit("interacted", props.item.recommendation_item_id);
  } catch (cause) {
    interactionError.value = cause instanceof Error ? cause.message : "跳过操作失败";
  } finally {
    acting.value = false;
  }
}

const profile = computed(() => props.item.profile ?? {});

const displayName = computed(() => profile.value.display_name ?? "VAV 会员");

const ageDisplay = computed(() => {
  const value = profile.value.age_display ?? profile.value.age;
  if (value === null || value === undefined || value === "") return "";
  return `${value} 岁`;
});

const cityDisplay = computed(
  () => profile.value.city_display ?? profile.value.city_code ?? profile.value.region_code ?? ""
);

const introduction = computed(
  () => profile.value.short_introduction ?? profile.value.self_introduction ?? ""
);

const photo = computed(() => profile.value.primary_photo ?? null);
const photoInitial = computed(() => displayName.value.slice(0, 1));
</script>

<template>
  <article class="recommendation-card">
    <header class="identity">
      <div
        class="photo"
        aria-hidden="true"
      >
        <span>{{ photoInitial }}</span>
      </div>
      <div class="identity-text">
        <h3>{{ displayName }}</h3>
        <p class="meta">
          <span v-if="ageDisplay">{{ ageDisplay }}</span>
          <span v-if="cityDisplay">· {{ cityDisplay }}</span>
          <span v-if="!ageDisplay && !cityDisplay">该会员未公开年龄或城市</span>
        </p>
        <p
          v-if="photo?.requires_view_token"
          class="photo-note"
        >
          照片需在对方授权后查看。
        </p>
      </div>
    </header>

    <p
      v-if="introduction"
      class="introduction"
    >
      {{ introduction }}
    </p>

    <CompatibilitySummary
      :explanation="item.explanation"
      :compact="!detailed"
    />

    <InformationGap :gaps="item.explanation.information_gaps" />

    <PreferenceRelaxationCard
      :notices="item.explanation.relaxation_notices"
      :preferences-path="preferencesPath"
    />

    <ExposureNotice
      :available-from="item.available_from"
      :expires-at="item.expires_at"
      :status="item.status"
    />

    <p
      v-if="interactionNotice"
      class="interaction-notice"
      role="status"
    >
      {{ interactionNotice }}
    </p>
    <p
      v-if="interactionError"
      class="interaction-error"
      role="alert"
    >
      {{ interactionError }}
    </p>

    <footer class="actions">
      <button
        v-if="detailPath || !detailed"
        type="button"
        class="primary"
        @click="emit('open', item.recommendation_item_id)"
      >
        查看完整推荐
      </button>
      <button
        type="button"
        :disabled="acting"
        @click="like"
      >
        感兴趣
      </button>
      <button
        type="button"
        :disabled="acting"
        @click="skip"
      >
        暂时跳过
      </button>
      <button
        type="button"
        class="quiet"
        @click="emit('not-relevant', item.recommendation_item_id)"
      >
        不合适
      </button>
    </footer>
  </article>
</template>

<style scoped>
.recommendation-card { display: flex; flex-direction: column; gap: 0.9rem; padding: 1.25rem; border: 1px solid rgba(0, 0, 0, 0.1); border-radius: 0.75rem; background: #fff; }
.identity { display: flex; gap: 0.9rem; align-items: center; }
.photo { width: 3.5rem; height: 3.5rem; border-radius: 999px; background: rgba(0, 0, 0, 0.08); display: grid; place-items: center; font-size: 1.25rem; font-weight: 600; }
.identity-text { display: flex; flex-direction: column; gap: 0.2rem; }
.identity-text h3 { margin: 0; font-size: 1.1rem; }
.meta { margin: 0; display: flex; gap: 0.35rem; flex-wrap: wrap; font-size: 0.9rem; opacity: 0.8; }
.photo-note { margin: 0; font-size: 0.78rem; opacity: 0.7; }
.introduction { margin: 0; line-height: 1.7; }
.actions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.actions button { padding: 0.45rem 1rem; border-radius: 0.5rem; border: 1px solid rgba(0, 0, 0, 0.15); background: transparent; cursor: pointer; font-size: 0.9rem; }
.actions button:disabled { opacity: 0.45; cursor: not-allowed; }
.actions button.primary { background: #1f2933; color: #fff; border-color: #1f2933; }
.actions button.quiet { border-style: dashed; }
.interaction-notice { margin: 0; padding: .6rem .8rem; border-radius: .5rem; background: #eaf6ec; color: #1c5a2a; }
.interaction-error { margin: 0; padding: .6rem .8rem; border-radius: .5rem; background: #fdecea; color: #8a1c12; }
</style>
