import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  recommendationFixtureDisplayNames,
  resetLoginRateLimits,
  seedRecommendationFixture,
  verifyUserFixture
} from "../helpers";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedRecommendationFixture();
});

const password = "VavRecommend!2026_Secure#";

async function signInNewMember(page: Page, prefix: string) {
  const email = `${prefix}-${Date.now()}@example.com`;
  await page.goto("/zh-CN/auth/register");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByLabel("我已阅读并同意服务条款与隐私说明").check();
  await page.getByRole("button", { name: "建立 VAV 账户" }).click();
  verifyUserFixture(email);
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱或账号").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/);
  await page.goto("/zh-CN/recommendations");
}

test("an empty day is explained with aggregate counts and never with another member", async ({
  page
}) => {
  await signInNewMember(page, "recommendation-empty");

  await expect(page.getByRole("heading", { name: "今天没有符合你条件的推荐" })).toBeVisible();
  await expect(
    page.getByText(
      "系统不会为了凑数而降低你设定的条件。以下说明只统计条件的排除次数，不涉及任何具体会员。"
    )
  ).toBeVisible();

  // Restrictive criteria are reported as a criterion code and a count, nothing else.
  const entries = await page.getByRole("listitem").allInnerTexts();
  for (const entry of entries.filter((text) => text.includes("排除"))) {
    expect(entry).toMatch(/^.+ · 排除 \d+ 位候选$/u);
  }
  await expect(
    page.getByText("这里只显示条件代码与数量，不会显示任何会员的身份或资料。")
  ).toHaveCount(
    await page.getByRole("heading", { name: "排除人数最多的条件" }).count()
  );

  for (const displayName of recommendationFixtureDisplayNames) {
    await expect(page.getByText(displayName)).toHaveCount(0);
  }
  await expect(page.getByRole("article")).toHaveCount(0);
  expect(await page.getByRole("main").innerText()).not.toMatch(/\d+\s*%/u);
});

test("the empty state offers the documented alternatives instead of lowering conditions", async ({
  page
}) => {
  await signInNewMember(page, "recommendation-empty-actions");

  await expect(page.getByRole("heading", { name: "你可以" })).toBeVisible();
  for (const action of [
    "检视最严格的择偶条件",
    "允许系统放宽部分条件",
    "等待新的档案通过审核",
    "先参加活动或课程"
  ]) {
    await expect(page.getByText(action)).toBeVisible();
  }
  await expect(
    page.getByRole("listitem").filter({ hasText: "暂停接收推荐" })
  ).toHaveCount(1);

  await expect(page.getByRole("link", { name: "调整推荐设置" })).toBeVisible();
  await expect(page.getByRole("link", { name: "修改择偶条件" })).toBeVisible();
  await expect(page.getByRole("link", { name: "去看看活动" })).toBeVisible();
  await expect(page.getByRole("button", { name: "暂停接收推荐" })).toBeVisible();
});

test("a member without an approved profile is told what to complete first", async ({ page }) => {
  await signInNewMember(page, "recommendation-empty-eligibility");

  await expect(page.getByRole("heading", { name: "暂时无法生成推荐" })).toBeVisible();
  await expect(page.getByText("尚未进入推荐池，请先完成并提交婚恋档案。")).toBeVisible();
  await expect(page.getByRole("link", { name: "前往婚恋档案" })).toBeVisible();
});
