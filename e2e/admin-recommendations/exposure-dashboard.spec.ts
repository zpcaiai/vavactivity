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

async function openExposures(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  await page.goto(`${adminBaseUrl}/admin/recommendations/exposures`);
  await expect(page.getByRole("heading", { name: "推荐运营中心" })).toBeVisible();
}

test("qualified exposure fairness is reported with coverage and concentration", async ({
  page
}) => {
  await openExposures(page);

  for (const metric of [
    "可推荐档案",
    "已曝光档案",
    "覆盖率 (bps)",
    "曝光基尼 (bps)",
    "从未曝光"
  ]) {
    await expect(page.getByText(metric).first()).toBeVisible();
  }
  await expect(
    page.getByRole("heading", { name: "曝光最多的档案（仅数量，不含身份）" })
  ).toBeVisible();

  // A fairness report is about counts; it never names the profiles it counts.
  for (const displayName of recommendationFixtureDisplayNames) {
    await expect(page.getByText(displayName)).toHaveCount(0);
  }
});

test("the overview links exposure fairness to the batches that produced it", async ({ page }) => {
  await openExposures(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/dashboard`);

  await expect(page.getByLabel("推荐总览")).toBeVisible();
  for (const metric of [
    "可推荐档案",
    "推荐池总量",
    "有效候选配对",
    "生效批次",
    "失败批次",
    "空结果批次",
    "曝光覆盖率 (bps)",
    "从未曝光档案",
    "负向反馈（聚合）",
    "冷启动会员"
  ]) {
    await expect(page.getByText(metric).first()).toBeVisible();
  }
});
