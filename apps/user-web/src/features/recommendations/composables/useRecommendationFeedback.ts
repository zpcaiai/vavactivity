import { ref } from "vue";

import { recommendationsApi } from "@/features/recommendations/api";
import type { FeedbackType } from "@/features/recommendations/types";

/** zh-CN copy for the reason codes the backend accepts with "不合适". */
export const FEEDBACK_REASON_LABELS: Record<string, string> = {
  location_not_suitable: "所在城市或距离不合适",
  faith_expectations_differ: "信仰期待不同",
  relationship_goals_differ: "关系目标不同",
  family_and_children_expectations_differ: "家庭与生育期待不同",
  lifestyle_not_suitable: "生活方式不合适",
  profile_information_insufficient: "资料信息太少，难以判断",
  not_looking_right_now: "我最近暂时不想认识新的人",
  prefer_not_to_say: "不方便说明",
  other: "其他原因"
};

export const DEFAULT_FEEDBACK_REASON_CODES: string[] = Object.keys(FEEDBACK_REASON_LABELS);

export function feedbackReasonText(code: string) {
  return FEEDBACK_REASON_LABELS[code] ?? code;
}

/**
 * Feedback a member may give from a recommendation card.
 *
 * Like and skip belong to Batch 15 (mutual selection) and are not sent from
 * here; this composable submits viewing signals and "不合适" only. Feedback is
 * used to tune the member's own list and is never shown to the other member.
 */
export function useRecommendationFeedback() {
  const submitting = ref(false);
  const error = ref("");
  const notice = ref("");
  const dialogOpen = ref(false);
  const activeItemId = ref<string>();

  function openDialog(itemId: string) {
    activeItemId.value = itemId;
    dialogOpen.value = true;
    error.value = "";
    notice.value = "";
  }

  function closeDialog() {
    dialogOpen.value = false;
    activeItemId.value = undefined;
  }

  async function submit(
    itemId: string,
    feedbackType: FeedbackType,
    reasonCode?: string | null,
    reasonDetails?: string | null
  ) {
    submitting.value = true;
    error.value = "";
    try {
      await recommendationsApi.submitFeedback(itemId, {
        feedback_type: feedbackType,
        reason_code: reasonCode ?? null,
        reason_details: reasonDetails ?? null
      });
      notice.value =
        feedbackType === "not_relevant"
          ? "已记录你的反馈，对方不会收到任何通知。"
          : "已记录浏览反馈。";
      return true;
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "反馈提交失败";
      return false;
    } finally {
      submitting.value = false;
    }
  }

  async function submitNotRelevant(
    itemId: string,
    reasonCode: string,
    reasonDetails?: string | null
  ) {
    const ok = await submit(itemId, "not_relevant", reasonCode, reasonDetails ?? null);
    if (ok) closeDialog();
    return ok;
  }

  return {
    submitting,
    error,
    notice,
    dialogOpen,
    activeItemId,
    openDialog,
    closeDialog,
    submit,
    submitNotRelevant
  };
}
