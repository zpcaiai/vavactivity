import { RouterLinkStub, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import RecommendationCard from "@/features/recommendations/components/RecommendationCard.vue";
import RecommendationEmptyState from "@/features/recommendations/components/RecommendationEmptyState.vue";
import {
  VISIBLE_THRESHOLD_MS,
  createExposureTracker
} from "@/features/recommendations/composables/useRecommendationExposure";
import type {
  ExposurePayload,
  RecommendationEmptyStateData,
  RecommendationItem
} from "@/features/recommendations/types";
import { router } from "@/router";

const interactionMocks = vi.hoisted(() => ({
  like: vi.fn(),
  skip: vi.fn()
}));

vi.mock("@/features/matchmaking-interactions/api", () => ({
  matchmakingInteractionsApi: interactionMocks
}));

const item: RecommendationItem = {
  recommendation_item_id: "11111111-1111-4111-8111-111111111111",
  rank_position: 1,
  status: "ready",
  profile: {
    profile_id: "22222222-2222-4222-8222-222222222222",
    display_name: "小恩",
    age_display: "32",
    city_display: "上海",
    primary_photo: { photo_id: "photo-1", status: "approved", requires_view_token: true },
    short_introduction: "喜欢周末去教会诗班练习，也常和朋友一起爬山。"
  },
  explanation: {
    summary: "你们在信仰生活和关系目标上有相近的期待。",
    mutual_strengths: [
      { explanation_code: "shared_faith_background", display_text: "你们有相近的信仰背景。" }
    ],
    relevant_preferences: [
      { explanation_code: "matches_age_range", display_text: "符合你设置的年龄范围。" }
    ],
    topics_to_explore: [
      { explanation_code: "topic_family_vision", display_text: "可以聊聊各自的家庭愿景。" }
    ],
    information_gaps: [
      { explanation_code: "gap_relocation", display_text: "对方尚未填写是否愿意搬迁。" }
    ],
    caveat: "推荐只是一个开始，是否合适仍需你们自己了解和判断。",
    relaxation_notices: ["age_range"]
  },
  available_from: "2026-08-04T01:00:00Z",
  expires_at: "2026-08-11T01:00:00Z"
};

const emptyState: RecommendationEmptyStateData = {
  available_actions: [
    "review_most_restrictive_criteria",
    "enable_allowed_relaxations",
    "browse_activities_or_courses",
    "pause_recommendations"
  ],
  most_restrictive_criteria: [
    { criterion_code: "city_code", excluded_count: 42 },
    { criterion_code: "age_range", excluded_count: 17 }
  ],
  cold_start: {
    types: ["sparse_preferences"],
    exploration_slots: 2,
    uses_platform_defaults: true,
    guidance_codes: ["add_three_to_five_important_criteria"],
    policy_version: "1.0.0"
  }
};

const globalStubs = { global: { stubs: { RouterLink: RouterLinkStub } } };

describe("recommendation card", () => {
  it("shows the approved profile summary and the caveat verbatim", () => {
    const wrapper = mount(RecommendationCard, { props: { item }, ...globalStubs });
    const text = wrapper.text();
    expect(text).toContain("小恩");
    expect(text).toContain("32 岁");
    expect(text).toContain("上海");
    expect(text).toContain("你们有相近的信仰背景。");
    expect(text).toContain(item.explanation.caveat);
    expect(text).toContain("对方尚未填写是否愿意搬迁。");
  });

  it("never renders a compatibility percentage, score or ranking number", () => {
    const wrapper = mount(RecommendationCard, { props: { item, detailed: true }, ...globalStubs });
    const text = wrapper.text();
    expect(text).not.toMatch(/\d+\s*%/);
    expect(text).not.toMatch(/\d+\s*分\b/);
    // The only place these words may appear is the boundary statement itself.
    const withoutBoundary = text.replace(
      "平台不提供匹配分数或百分比，也不会展示对方对你的评价。",
      ""
    );
    expect(withoutBoundary).not.toMatch(/匹配度|契合度|评分|得分|分数|排名|score/i);
    // The rank position exists in the payload but must never reach the member.
    expect(text).not.toContain("第 1 位");
    expect(text).toContain("平台不提供匹配分数或百分比");
  });

  it("records a private like and reports a mutual match only from the outcome field", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    interactionMocks.like.mockResolvedValueOnce({ outcome: "mutual_match" });
    const wrapper = mount(RecommendationCard, { props: { item }, ...globalStubs });
    await wrapper.get("button:nth-of-type(2)").trigger("click");
    await vi.waitFor(() => expect(interactionMocks.like).toHaveBeenCalledWith(item.recommendation_item_id));
    expect(wrapper.text()).toContain("你们已经双方互选");
    expect(wrapper.emitted("interacted")?.[0]).toEqual([item.recommendation_item_id]);
  });

  it("records a private skip without notifying the other member", async () => {
    interactionMocks.skip.mockResolvedValueOnce({ outcome: "skipped" });
    const wrapper = mount(RecommendationCard, { props: { item }, ...globalStubs });
    await wrapper.get("button:nth-of-type(3)").trigger("click");
    await vi.waitFor(() => expect(interactionMocks.skip).toHaveBeenCalledWith(
      item.recommendation_item_id,
      { skip_type: "not_now" }
    ));
    expect(wrapper.text()).toContain("对方不会看到这个选择");
  });

  it("keeps the not-relevant feedback action available", async () => {
    const wrapper = mount(RecommendationCard, { props: { item }, ...globalStubs });
    const buttons = wrapper.findAll("button");

    const notRelevant = buttons.find((button) => button.text() === "不合适");
    expect(notRelevant?.attributes("disabled")).toBeUndefined();
    await notRelevant?.trigger("click");
    expect(wrapper.emitted("not-relevant")?.[0]).toEqual([item.recommendation_item_id]);
  });
});

describe("exposure threshold", () => {
  function tracker() {
    const send = vi.fn<(itemId: string, payload: ExposurePayload) => void>();
    return { send, instance: createExposureTracker({ send, now: () => 0 }) };
  }

  it("reports one impression per item when the card mounts", () => {
    const { send, instance } = tracker();
    expect(instance.impression("item-1")).toBe(true);
    expect(instance.impression("item-1")).toBe(false);
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith(
      "item-1",
      expect.objectContaining({ exposure_type: "card_impression", duration_ms: null })
    );
  });

  it("does not report card_visible before 1000ms of continuous visibility", () => {
    const { send, instance } = tracker();
    instance.enter("item-1", 0);
    expect(instance.tick(VISIBLE_THRESHOLD_MS - 1)).toEqual([]);
    expect(instance.leave("item-1", 999)).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it("reports card_visible once with the measured duration after the threshold", () => {
    const { send, instance } = tracker();
    instance.enter("item-1", 0);
    expect(instance.tick(1200)).toEqual(["item-1"]);
    expect(send).toHaveBeenCalledWith(
      "item-1",
      expect.objectContaining({ exposure_type: "card_visible", duration_ms: 1200 })
    );
    // De-duplicated per item + type: further ticks and leaves send nothing.
    expect(instance.tick(3000)).toEqual([]);
    expect(instance.leave("item-1", 4000)).toBe(false);
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("restarts the timer when visibility is interrupted", () => {
    const { send, instance } = tracker();
    instance.enter("item-1", 0);
    instance.leave("item-1", 600);
    instance.enter("item-1", 600);
    expect(instance.tick(1000)).toEqual([]);
    expect(instance.tick(1700)).toEqual(["item-1"]);
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith(
      "item-1",
      expect.objectContaining({ exposure_type: "card_visible", duration_ms: 1100 })
    );
  });
});

describe("recommendation empty state", () => {
  it("renders the backend actions, criterion counts and adjustment links", () => {
    const wrapper = mount(RecommendationEmptyState, {
      props: {
        emptyState,
        preferencesPath: "/zh-CN/account/recommendation-preferences",
        datingPreferencesPath: "/zh-CN/account/dating-profile/preferences",
        activitiesPath: "/zh-CN/activities"
      },
      ...globalStubs
    });
    const text = wrapper.text();

    expect(text).toContain("今天没有符合你条件的推荐");
    expect(text).toContain("检视最严格的择偶条件");
    expect(text).toContain("允许系统放宽部分条件");
    expect(text).toContain("先参加活动或课程");
    expect(text).toContain("所在城市 · 排除 42 位候选");
    expect(text).toContain("年龄范围 · 排除 17 位候选");
    expect(text).toContain("填写的择偶条件较少");

    const links = wrapper.findAllComponents(RouterLinkStub).map((link) => link.props("to"));
    expect(links).toEqual(
      expect.arrayContaining([
        "/zh-CN/account/recommendation-preferences",
        "/zh-CN/account/dating-profile/preferences",
        "/zh-CN/activities"
      ])
    );
  });

  it("offers pausing recommendations from the empty state", async () => {
    const wrapper = mount(RecommendationEmptyState, {
      props: {
        emptyState,
        preferencesPath: "/zh-CN/account/recommendation-preferences",
        activitiesPath: "/zh-CN/activities"
      },
      ...globalStubs
    });
    await wrapper.get("button").trigger("click");
    expect(wrapper.emitted("pause")).toHaveLength(1);
  });
});

describe("recommendation routes", () => {
  it("registers the locale-prefixed recommendation routes", () => {
    const names = router.getRoutes().map((route) => route.name);
    expect(names).toEqual(
      expect.arrayContaining([
        "recommendations",
        "recommendation-detail",
        "account-recommendation-preferences",
        "account-recommendation-history",
        "account-recommendation-transparency"
      ])
    );
    const detail = router.getRoutes().find((route) => route.name === "recommendation-detail");
    expect(detail?.path).toBe("/:locale(zh-CN|zh-TW|en)/recommendations/:recommendationItemId");
    expect(detail?.meta.requiresAuth).toBe(true);
  });
});
