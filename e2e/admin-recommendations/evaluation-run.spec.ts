import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  recommendationCandidateStrategyCode,
  resetLoginRateLimits,
  seedRecommendationCandidateStrategy,
  seedRecommendationFixture,
  seedSuperAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";
const datasetCode = "recommendation-baseline-synthetic";

let candidateStrategyId = "";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedSuperAdmin();
  seedRecommendationFixture();
  candidateStrategyId = seedRecommendationCandidateStrategy();
});

async function openEvaluations(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  await page.goto(`${adminBaseUrl}/admin/recommendations/evaluations`);
  await expect(page.getByRole("heading", { name: "推荐运营中心" })).toBeVisible();
}

async function runEvaluation(page: Page) {
  await page.getByLabel("评估数据集代码").fill(datasetCode);
  await page.getByLabel("待评估策略 ID").fill(candidateStrategyId);
  await page.getByRole("button", { name: "运行评估" }).click();
  await expect(page.getByText("离线评估已执行。阻断项未通过的策略无法上线。")).toBeVisible();
}

test("an evaluation run reports its status, blocking failures and guardrail failures", async ({
  page
}) => {
  await openEvaluations(page);
  await expect(
    page.getByText("离线评估是策略上线的前置条件：阻断项未通过的版本不能上线。")
  ).toBeVisible();

  // A run always names the dataset and the version it judged.
  await page.getByRole("button", { name: "运行评估" }).click();
  await expect(page.getByText("请填写评估数据集代码与策略 ID。")).toBeVisible();

  await runEvaluation(page);

  for (const column of ["status", "blocking_failures", "guardrail_failures", "dataset_code"]) {
    await expect(page.getByText(column).first()).toBeVisible();
  }
  await expect(page.getByText(datasetCode).first()).toBeVisible();
});

test("the evaluation record is what a release is checked against", async ({ page }) => {
  await openEvaluations(page);
  await runEvaluation(page);

  await page.goto(`${adminBaseUrl}/admin/recommendations/strategies`);
  await page
    .getByRole("row")
    .filter({ hasText: recommendationCandidateStrategyCode })
    .getByRole("button", { name: "查看" })
    .click();

  await expect(page.getByRole("heading", { name: "评估记录" })).toBeVisible();
  await expect(page.getByText(/阻断项 \[.*\] · 护栏 \[.*\]/)).toBeVisible();
  await expect(page.getByText("尚无评估记录，该版本不可上线。")).toHaveCount(0);
});
