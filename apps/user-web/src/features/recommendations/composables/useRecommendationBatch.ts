import { ref } from "vue";

import { recommendationsApi } from "@/features/recommendations/api";
import type { BatchRequestResult } from "@/features/recommendations/types";

export const BATCH_TYPE_LABELS: Record<string, string> = {
  daily: "每日推荐",
  supplemental: "补充推荐",
  manual_rebuild: "人工重建"
};

export const BATCH_STATUS_LABELS: Record<string, string> = {
  generating: "生成中",
  ready: "可查看",
  delivered: "已送达",
  expired: "已过期",
  invalidated: "已失效"
};

export function batchTypeText(code: string) {
  return BATCH_TYPE_LABELS[code] ?? code;
}

export function batchStatusText(code: string) {
  return BATCH_STATUS_LABELS[code] ?? code;
}

/**
 * Requests today's batch.
 *
 * Repeat requests return the batch that already exists, so refreshing can never
 * add recommendations beyond the daily budget the member configured.
 */
export function useRecommendationBatch() {
  const requesting = ref(false);
  const error = ref("");
  const notice = ref("");
  const result = ref<BatchRequestResult>();

  async function requestBatch(
    batchType: "daily" | "supplemental" = "daily",
    requestedSize?: number
  ) {
    requesting.value = true;
    error.value = "";
    notice.value = "";
    try {
      result.value = await recommendationsApi.requestBatch({
        batch_type: batchType,
        requested_size: requestedSize ?? null
      });
      notice.value = `已获取${batchTypeText(result.value.batch_type)}，共 ${result.value.generated_size} 位。重复请求不会超出每日数量上限。`;
      return result.value;
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "获取推荐失败";
      return undefined;
    } finally {
      requesting.value = false;
    }
  }

  return { requesting, error, notice, result, requestBatch };
}
