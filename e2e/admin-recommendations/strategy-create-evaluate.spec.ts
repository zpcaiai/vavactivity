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

test.beforeAll(() => {
  resetLoginRateLimits();
  seedSuperAdmin();
  seedRecommendationFixture();
  // A version parked in `evaluating` with no evaluation run at all.
  seedRecommendationCandidateStrategy();
});

async function signIn(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
}

test("a version without a passing offline evaluation cannot be released", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/strategies`);
  await expect(
    page.getByRole("heading", { name: "推荐运营中心", level: 2 })
  ).toBeVisible();
  await expect(
    page.getByText(
      "上线前置条件：必须存在通过的离线评估，且审批人与上线人必须是不同的管理员。后端会再次校验，前端不提供跳过入口。"
    )
  ).toBeVisible();

  await page.getByLabel("操作原因").fill("e2e 发布门槛验证");
  const candidateRow = page
    .getByRole("row")
    .filter({ hasText: recommendationCandidateStrategyCode });
  await candidateRow.getByRole("button", { name: "审批" }).click();

  await expect(
    page.getByText("A strategy needs a passing offline evaluation before release.")
  ).toBeVisible();
  await expect(candidateRow).toContainText("evaluating");
});

test("the version detail states that it has no evaluation record yet", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/strategies`);

  await page
    .getByRole("row")
    .filter({ hasText: recommendationCandidateStrategyCode })
    .getByRole("button", { name: "查看" })
    .click();

  await expect(
    page.getByRole("heading", { name: `策略 ${recommendationCandidateStrategyCode}` })
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "评估记录" })).toBeVisible();
  await expect(page.getByText("尚无评估记录，该版本不可上线。")).toBeVisible();
});

test("the operations centre offers no way to hand-edit a score or a hard constraint", async ({
  page
}) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/features`);
  await expect(
    page.getByText(
      "特征注册表是只读的：权重、评分函数与版本由策略版本决定，运营不能在此处改分。"
    )
  ).toBeVisible();
  await expect(page.getByText("默认权重")).toBeVisible();

  await page.goto(`${adminBaseUrl}/admin/recommendations/constraints`);
  await expect(
    page.getByText("硬性条件只能由策略版本定义，运营无法为单次推荐绕过任何一条。")
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "支持的硬性条件代码" })).toBeVisible();
});
