import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  recommendationFixtureEmail,
  recommendationFixturePassword,
  resetLoginRateLimits,
  seedRecommendationFixture
} from "../helpers";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedRecommendationFixture();
});

async function openFirstRecommendation(page: Page) {
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱或账号").fill(recommendationFixtureEmail("jonathan"));
  await page.getByLabel("密码").fill(recommendationFixturePassword);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/);
  await page.goto("/zh-CN/recommendations");
  await page.getByRole("button", { name: "查看完整推荐" }).first().click();
  await expect(page).toHaveURL(/\/zh-CN\/recommendations\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: "推荐详情" })).toBeVisible();
}

test("the detail view explains the match through mutual strengths and the viewer's own conditions", async ({
  page
}) => {
  await openFirstRecommendation(page);

  const card = page.getByRole("article").first();
  await expect(card.getByRole("heading", { name: "你们的共同点" })).toBeVisible();

  // The detail view is the only place the two viewer-scoped groups are rendered;
  // the backend omits a group entirely when it has nothing to say.
  const ownPreferences = card.getByRole("heading", { name: "与你设置的择偶条件相关" });
  const topics = card.getByRole("heading", { name: "可以聊聊的话题" });
  await expect(ownPreferences.or(topics).first()).toBeVisible();

  // Whenever the preference group appears it must say the list is the viewer's own.
  await expect(
    card.getByText("这里只显示你自己填写的条件，不会显示对方的择偶条件。")
  ).toHaveCount(await ownPreferences.count());

  await expect(card.getByRole("heading", { name: "尚未确认的信息" })).toBeVisible();
  await expect(
    card.getByText("推荐只是认识的机会，最终判断由你自己作出；平台不对结果作任何保证。")
  ).toBeVisible();
  await expect(
    card.getByText(
      "平台不提供匹配分数或百分比，也不会展示对方对你的评价。是否继续了解，由你自己决定。"
    )
  ).toBeVisible();

  await expect(
    page.getByText(
      "联系方式、精确出生日期和对方的择偶条件不会在此展示。感兴趣与暂时跳过不会向对方公开；只有双方都感兴趣时才会建立互选。"
    )
  ).toBeVisible();
});

test("like and skip are available while every one-sided choice stays private", async ({
  page
}) => {
  await openFirstRecommendation(page);

  const card = page.getByRole("article").first();
  await expect(card.getByRole("button", { name: "感兴趣", exact: true })).toBeEnabled();
  await expect(card.getByRole("button", { name: "暂时跳过", exact: true })).toBeEnabled();
  await expect(card.getByRole("button", { name: "不合适" })).toBeEnabled();

  await card.getByRole("button", { name: "不合适" }).click();
  await expect(page.getByRole("dialog")).toContainText("这条推荐不合适");
  await expect(page.getByRole("dialog")).toContainText(
    "你的反馈只用于调整你自己收到的推荐，对方不会收到任何通知，也看不到反馈内容。"
  );
  await page.getByRole("button", { name: "取消" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
