<script setup lang="ts">
import { ref, watch } from "vue";

import {
  DEFAULT_FEEDBACK_REASON_CODES,
  feedbackReasonText
} from "@/features/recommendations/composables/useRecommendationFeedback";

/**
 * The "不合适" dialog.
 *
 * This is the only feedback a member sends from a card in this batch. Like and
 * skip belong to the mutual-selection batch and are rendered as disabled
 * placeholders on the card itself.
 */
const props = defineProps<{
  open: boolean;
  reasonCodes?: string[];
  submitting?: boolean;
  error?: string;
}>();

const emit = defineEmits<{
  (event: "submit", payload: { reasonCode: string; reasonDetails: string }): void;
  (event: "close"): void;
}>();

const reasonCode = ref("");
const reasonDetails = ref("");

watch(
  () => props.open,
  (open) => {
    if (!open) return;
    reasonCode.value = "";
    reasonDetails.value = "";
  }
);

function submit() {
  if (!reasonCode.value) return;
  emit("submit", { reasonCode: reasonCode.value, reasonDetails: reasonDetails.value });
}
</script>

<template>
  <div
    v-if="open"
    class="dialog-backdrop"
  >
    <div
      class="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="feedback-dialog-title"
    >
      <h2 id="feedback-dialog-title">
        这条推荐不合适
      </h2>
      <p class="hint">
        你的反馈只用于调整你自己收到的推荐，对方不会收到任何通知，也看不到反馈内容。
      </p>

      <fieldset>
        <legend>请选择原因</legend>
        <label
          v-for="code in reasonCodes?.length ? reasonCodes : DEFAULT_FEEDBACK_REASON_CODES"
          :key="code"
          class="option"
        >
          <input
            v-model="reasonCode"
            type="radio"
            name="feedback-reason"
            :value="code"
          >
          {{ feedbackReasonText(code) }}
        </label>
      </fieldset>

      <label
        class="details"
        for="feedback-reason-details"
      >补充说明（可选）</label>
      <textarea
        id="feedback-reason-details"
        v-model="reasonDetails"
        rows="3"
        maxlength="2000"
        placeholder="请勿填写联系方式或对他人的评价。"
      />

      <p
        v-if="error"
        class="alert error"
        role="alert"
      >
        {{ error }}
      </p>

      <div class="actions">
        <button
          type="button"
          class="primary"
          :disabled="!reasonCode || submitting"
          @click="submit"
        >
          {{ submitting ? "提交中…" : "提交反馈" }}
        </button>
        <button
          type="button"
          @click="emit('close')"
        >
          取消
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dialog-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35); display: grid; place-items: center; padding: 1rem; z-index: 50; }
.dialog { width: min(32rem, 100%); max-height: calc(100vh - 2rem); overflow-y: auto; background: var(--vav-color-surface-raised); border-radius: 0.75rem; padding: 1.5rem; display: flex; flex-direction: column; gap: 0.75rem; }
.dialog h2 { margin: 0; font-size: 1.05rem; }
.hint { font-size: 0.85rem; opacity: 0.75; line-height: 1.6; margin: 0; }
fieldset { border: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.35rem; }
legend { font-weight: 600; font-size: 0.9rem; padding: 0 0 0.35rem; }
.option { display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; }
.details { font-weight: 600; font-size: 0.9rem; }
textarea { width: 100%; padding: 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(0, 0, 0, 0.2); }
.alert.error { background: var(--vav-color-surface-danger); color: var(--vav-color-danger); padding: 0.6rem 0.8rem; border-radius: 0.5rem; margin: 0; }
.actions { display: flex; gap: 0.5rem; }
.actions button { padding: 0.5rem 1.2rem; border-radius: 0.5rem; border: 1px solid rgba(0, 0, 0, 0.15); background: transparent; cursor: pointer; }
.actions button.primary { background: var(--vav-color-text); color: var(--vav-color-surface-raised); border-color: var(--vav-color-text); }
.actions button.primary:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
