import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  recommendationFixtureDisplayNames,
  resetLoginRateLimits,
  seedRecommendationFixture,
  seedSuperAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedSuperAdmin();
  seedRecommendationFixture();
});

async function openColdStart(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  await page.goto(`${adminBaseUrl}/admin/recommendations/cold-start`);
  await expect(page.getByRole("heading", { name: "推荐运营中心" })).toBeVisible();
}

test("the cold-start view reports who the engine cannot personalise yet", async ({ page }) => {
  await openColdStart(page);

  await expect(page.getByLabel("冷启动总览")).toBeVisible();
  for (const metric of [
    "可推荐档案",
    "条件过少会员",
    "近 14 天新档案",
    "从未曝光档案"
  ]) {
    await expect(page.getByText(metric).first()).toBeVisible();
  }

  // Cold start is a population measure, not a list of members.
  for (const displayName of recommendationFixtureDisplayNames) {
    await expect(page.getByText(displayName)).toHaveCount(0);
  }
});

test("cold-start members are still counted in the aggregate feedback view", async ({ page }) => {
  await openColdStart(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/feedback`);

  await expect(
    page.getByText(
      "只展示聚合计数。用户填写的自由文本理由保持加密私有，本页面从不请求，也没有查看入口。"
    )
  ).toBeVisible();
  for (const metric of ["反馈总量", "负向反馈", "举报", "屏蔽"]) {
    await expect(page.getByText(metric).first()).toBeVisible();
  }
});
