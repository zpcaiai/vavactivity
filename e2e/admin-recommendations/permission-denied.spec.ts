import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  recommendationOperatorEmail,
  recommendationOperatorPassword,
  resetLoginRateLimits,
  seedRecommendationFixture,
  seedRecommendationOperator
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedRecommendationFixture();
  // Role `recommendation_operator`: monitoring only, no sensitive or experiment scope.
  seedRecommendationOperator();
});

async function signInOperator(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(recommendationOperatorEmail);
  await page.getByLabel("密码").fill(recommendationOperatorPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
}

test("an operator without the sensitive permission is refused the pair diagnostics", async ({
  page
}) => {
  await signInOperator(page);

  await page.goto(`${adminBaseUrl}/admin/recommendations/pair-diagnostics`);
  await expect(page).toHaveURL(/\/admin\/403$/);
  await expect(page.getByRole("heading", { name: "没有访问权限" })).toBeVisible();
  await expect(
    page.getByText("当前账户没有执行此操作所需的服务端权限。")
  ).toBeVisible();
});

test("sections the operator may not read are refused as well", async ({ page }) => {
  await signInOperator(page);

  for (const section of ["experiments", "incidents"]) {
    await page.goto(`${adminBaseUrl}/admin/recommendations/${section}`);
    await expect(page).toHaveURL(/\/admin\/403$/);
    await expect(page.getByRole("heading", { name: "没有访问权限" })).toBeVisible();
  }
});

test("the monitoring sections the operator may read stay available", async ({ page }) => {
  await signInOperator(page);

  await page.goto(`${adminBaseUrl}/admin/recommendations/dashboard`);
  await expect(page.getByRole("heading", { name: "推荐运营中心" })).toBeVisible();
  await expect(page.getByLabel("推荐总览")).toBeVisible();

  // The tab strip only offers what this operator is allowed to open.
  await expect(page.getByRole("tab", { name: "总览" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "曝光公平" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "配对诊断（敏感）" })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "实验" })).toHaveCount(0);
});
