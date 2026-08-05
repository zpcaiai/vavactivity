import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  recommendationExperimentCode,
  resetLoginRateLimits,
  seedBreachingRecommendationExperiment,
  seedRecommendationFixture,
  seedSuperAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedSuperAdmin();
  seedRecommendationFixture();
  // A running experiment whose guardrail threshold is already exceeded.
  seedBreachingRecommendationExperiment();
});

async function openExperiments(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  await page.goto(`${adminBaseUrl}/admin/recommendations/experiments`);
  await expect(page.getByRole("heading", { name: "推荐运营中心" })).toBeVisible();
}

test("a breached guardrail stops the running treatment and records why", async ({ page }) => {
  await openExperiments(page);

  const experimentRow = page.getByRole("row").filter({ hasText: recommendationExperimentCode });
  await expect(experimentRow).toContainText("running");

  await experimentRow.getByRole("button", { name: "护栏检查" }).click();
  await expect(page.getByText("护栏检查完成：已触发自动停止。")).toBeVisible();

  await expect(experimentRow).toContainText("stopped");
  await expect(experimentRow).toContainText("guardrail_breached:report_rate_bps");
});

test("a stopped experiment cannot be started again", async ({ page }) => {
  await openExperiments(page);

  const experimentRow = page.getByRole("row").filter({ hasText: recommendationExperimentCode });
  await experimentRow.getByRole("button", { name: "护栏检查" }).click();
  await expect(experimentRow).toContainText("stopped");

  await page.getByLabel("操作原因").fill("e2e 停止后不可重启验证");
  await experimentRow.getByRole("button", { name: "启动" }).click();
  await expect(
    page.getByText("An experiment cannot move from stopped to running.")
  ).toBeVisible();
  await expect(experimentRow).toContainText("stopped");
});

test("experiments are described as off by default and approval gated", async ({ page }) => {
  await openExperiments(page);

  await expect(
    page.getByText(
      "实验默认关闭：新建后必须先审批才能启动，护栏指标越界会立即停止实验并写入审计。"
    )
  ).toBeVisible();
  await expect(
    page.getByText(
      "运营人员只监督引擎：这里没有指定两个人配对、手工改分、绕过硬性条件或查看会员择偶条件原文的入口。"
    )
  ).toBeVisible();
});
