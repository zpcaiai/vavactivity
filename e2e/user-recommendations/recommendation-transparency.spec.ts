import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  recommendationFixtureDisplayNames,
  recommendationFixtureEmail,
  recommendationFixturePassword,
  resetLoginRateLimits,
  seedRecommendationFixture
} from "../helpers";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedRecommendationFixture();
});

async function openTransparency(page: Page) {
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱或账号").fill(recommendationFixtureEmail("hannah"));
  await page.getByLabel("密码").fill(recommendationFixturePassword);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/);
  await page.goto("/zh-CN/account/recommendation-transparency");
  await expect(page.getByRole("heading", { name: "推荐是怎么产生的" })).toBeVisible();
}

test("the page names every data category the engine used", async ({ page }) => {
  await openTransparency(page);

  await expect(page.getByRole("heading", { name: "推荐使用了哪些资料类别" })).toBeVisible();
  for (const category of [
    "信仰与价值观",
    "所在地与搬迁意愿",
    "关系目标",
    "家庭与生育",
    "生活方式",
    "兴趣爱好",
    "沟通方式",
    "语言",
    "教育与工作",
    "档案完整度"
  ]) {
    await expect(page.getByText(category).first()).toBeVisible();
  }
  await expect(
    page.getByText(
      "推荐只使用你和对方已批准展示的档案资料，不使用照片外貌、聊天内容或消费记录。"
    )
  ).toBeVisible();
});

test("the never-used list covers AI conversations, counselling records and payments", async ({
  page
}) => {
  await openTransparency(page);

  await expect(page.getByRole("heading", { name: "永远不会被使用的资料" })).toBeVisible();
  for (const category of [
    "照片外貌评分",
    "你与 AI 辅导的对话内容",
    "真人辅导记录",
    "消费与付款记录",
    "健康状况或性格推断"
  ]) {
    await expect(page.getByText(category)).toBeVisible();
  }
});

test("the page separates the member's own conditions from the platform defaults", async ({
  page
}) => {
  await openTransparency(page);

  await expect(page.getByRole("heading", { name: "来自你自己填写的条件" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "使用平台默认设置的部分" })).toBeVisible();
  await expect(
    page.getByText("平台默认设置对所有会员一致，你填写的条件会优先于默认设置。")
  ).toBeVisible();

  await expect(page.getByRole("heading", { name: "你要求必须满足的条件" })).toBeVisible();
  await expect(page.getByText("年龄范围")).toBeVisible();
  await expect(
    page.getByText("这些条件不会被系统放宽，除非你在推荐设置中明确允许。")
  ).toBeVisible();

  await expect(page.getByRole("heading", { name: "基于浏览行为的个性化" })).toBeVisible();
  await expect(page.getByText(/当前状态：(已开启|已关闭)。/)).toBeVisible();

  await expect(page.getByRole("heading", { name: "如何调整" })).toBeVisible();
  for (const action of [
    "更新婚恋档案中的择偶条件",
    "修改允许系统放宽的条件",
    "调整推荐的探索程度",
    "关闭基于浏览行为的个性化"
  ]) {
    await expect(page.getByText(action)).toBeVisible();
  }

  // The page describes this member's own account and never another member.
  for (const displayName of recommendationFixtureDisplayNames) {
    await expect(page.getByText(displayName)).toHaveCount(0);
  }
});
