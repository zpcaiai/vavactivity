import { computed, ref } from "vue";

import { recommendationsApi } from "@/features/recommendations/api";
import type { RecommendationFeed, RecommendationItem } from "@/features/recommendations/types";

/** zh-CN copy for the eligibility reason codes the backend may return. */
export const INELIGIBLE_REASON_LABELS: Record<string, string> = {
  no_pool_entry: "尚未进入推荐池，请先完成并提交婚恋档案。",
  profile_not_approved: "婚恋档案尚未通过审核。",
  profile_paused: "婚恋档案已暂停，暂不参与推荐。",
  profile_incomplete: "婚恋档案还有必填内容未完成。",
  privacy_hidden: "隐私设置中已关闭“参与匹配”。",
  email_not_verified: "邮箱尚未验证。",
  safety_restriction: "账户当前处于安全限制中，请联系客服。",
  recommendations_paused: "你已暂停接收推荐。"
};

export function ineligibleReasonText(code: string) {
  return INELIGIBLE_REASON_LABELS[code] ?? code;
}

/**
 * zh-CN copy for partner-preference criterion codes.
 *
 * These describe the viewer's own conditions. The other member's preference
 * list is never returned by the API and never rendered.
 */
export const CRITERION_LABELS: Record<string, string> = {
  age_range: "年龄范围",
  age_years: "年龄",
  age_bucket: "年龄区间",
  city_code: "所在城市",
  region_code: "所在省份或地区",
  country_code: "所在国家",
  relocation_willingness: "是否愿意搬迁",
  faith_status_code: "信仰状态",
  church_tradition_codes: "教会传统",
  marriage_faith_importance: "信仰在婚姻中的重要性",
  relationship_intent: "关系目标",
  marital_status_code: "婚姻状况",
  open_to_partner_with_children: "是否接受对方有孩子",
  desire_children_code: "生育意愿",
  education_level_code: "学历",
  occupation_category_code: "职业方向",
  daily_schedule_code: "作息习惯",
  smoking_status_code: "吸烟情况",
  alcohol_use_code: "饮酒情况",
  exercise_frequency_code: "运动频率",
  travel_frequency_code: "出行频率",
  leisure_interest_codes: "兴趣爱好",
  communication_preference_codes: "沟通方式偏好",
  social_style_codes: "社交风格",
  language_codes: "语言",
  gender_code: "性别",
  eligible_partner_gender_codes: "希望认识的性别"
};

export function criterionText(code: string) {
  return CRITERION_LABELS[code] ?? code;
}

/**
 * Loads the viewer's own recommendation feed.
 *
 * The feed is produced by the backend for this member only: it contains no
 * score, no percentage and nothing about how the other member rated them.
 */
export function useRecommendations() {
  const feed = ref<RecommendationFeed>();
  const loading = ref(false);
  const error = ref("");

  const items = computed<RecommendationItem[]>(() => feed.value?.items ?? []);
  const batch = computed(() => feed.value?.batch ?? null);
  const emptyState = computed(() => feed.value?.empty_state ?? null);
  const eligible = computed(() => feed.value?.eligible === true);
  const paused = computed(() => feed.value?.recommendations_paused === true);
  const ineligibleReasons = computed(() => feed.value?.ineligible_reason_codes ?? []);

  async function load() {
    loading.value = true;
    error.value = "";
    try {
      feed.value = await recommendationsApi.list();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "推荐加载失败";
    } finally {
      loading.value = false;
    }
  }

  function itemById(itemId: string) {
    return items.value.find((item) => item.recommendation_item_id === itemId);
  }

  return {
    feed,
    items,
    batch,
    emptyState,
    eligible,
    paused,
    ineligibleReasons,
    loading,
    error,
    load,
    itemById
  };
}
