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
const baselineStrategyCode = "baseline-bidirectional-v1";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedSuperAdmin();
  seedRecommendationFixture();
  seedRecommendationCandidateStrategy();
});

async function signIn(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
}

test("activation cannot skip approval, even with a reason on file", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/strategies`);

  await page.getByLabel("操作原因").fill("e2e 上线顺序验证");
  const candidateRow = page
    .getByRole("row")
    .filter({ hasText: recommendationCandidateStrategyCode });
  await candidateRow.getByRole("button", { name: "上线" }).click();

  await expect(
    page.getByText("A strategy cannot move from evaluating to active.")
  ).toBeVisible();
  await expect(candidateRow).toContainText("evaluating");
});

test("a rollback is refused until an auditable reason is recorded", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/strategies`);

  const activeRow = page.getByRole("row").filter({ hasText: baselineStrategyCode });
  await expect(activeRow.first()).toContainText("active");

  // The reason box starts empty; rolling back without one is rejected up front.
  await activeRow.first().getByRole("button", { name: "回滚" }).click();
  await expect(
    page.getByText(
      "请先填写操作原因（至少 3 个字符）。原因会写入推荐审计，无法事后补填。"
    )
  ).toBeVisible();
  await expect(activeRow.first()).toContainText("active");

  // Two characters are still not a reason.
  await page.getByLabel("操作原因").fill("ab");
  await activeRow.first().getByRole("button", { name: "回滚" }).click();
  await expect(
    page.getByText(
      "请先填写操作原因（至少 3 个字符）。原因会写入推荐审计，无法事后补填。"
    )
  ).toBeVisible();
  await expect(activeRow.first()).toContainText("active");
});

test("the release rules are stated where the release buttons are", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/strategies`);

  await expect(
    page.getByText(
      "上线前置条件：必须存在通过的离线评估，且审批人与上线人必须是不同的管理员。后端会再次校验，前端不提供跳过入口。"
    )
  ).toBeVisible();
  await expect(
    page.getByText(
      "运营人员只监督引擎：这里没有指定两个人配对、手工改分、绕过硬性条件或查看会员择偶条件原文的入口。"
    )
  ).toBeVisible();
  await expect(page.getByLabel("操作原因")).toHaveAttribute(
    "placeholder",
    "操作原因（重建、作废、策略与实验状态变更必填，至少 3 个字符，写入审计）"
  );
});
