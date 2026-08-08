import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  recommendationCandidatePairId,
  recommendationFixtureDisplayNames,
  recommendationFixtureUserId,
  resetLoginRateLimits,
  seedRecommendationFixture,
  seedSuperAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

let fixtureUserId = "";
let candidatePairId = "";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedSuperAdmin();
  seedRecommendationFixture();
  fixtureUserId = recommendationFixtureUserId("mei");
  candidatePairId = recommendationCandidatePairId();
});

async function signIn(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
}

test("candidate statistics are aggregate counts with no member in them", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/candidates`);

  await expect(page.getByText("候选统计只显示聚合数量，不列出任何会员身份。")).toBeVisible();
  await expect(page.getByText(/配对状态 \w+/).first()).toBeVisible();
  for (const displayName of recommendationFixtureDisplayNames) {
    await expect(page.getByText(displayName)).toHaveCount(0);
  }
});

test("funnel diagnostics return counts and criterion codes only", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/diagnostics`);

  await expect(
    page.getByText(
      "漏斗诊断只返回聚合数量与条件代码：不会显示候选人身份，也不会显示会员填写的择偶条件原文。"
    )
  ).toBeVisible();

  await page.getByLabel("诊断用户 ID").fill(fixtureUserId);
  await page.getByRole("button", { name: "运行诊断" }).click();

  await expect(
    page.getByText("诊断已生成：仅包含聚合数量与条件代码，不包含任何候选人身份。")
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "漏斗数量" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "冷启动判定" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "空结果说明" })).toBeVisible();
  for (const displayName of recommendationFixtureDisplayNames) {
    await expect(page.getByText(displayName)).toHaveCount(0);
  }
});

test("pair diagnostics are gated on the sensitive permission and show codes only", async ({
  page
}) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/pair-diagnostics`);

  await expect(
    page.getByText(
      "配对诊断需要独立的敏感权限，每次查看都会记录敏感访问；只显示特征代码、通过结果、调整项与版本号，不显示任何档案内容。"
    )
  ).toBeVisible();

  await page.getByLabel("候选配对 ID").fill(candidatePairId);
  await page.getByRole("button", { name: "查看配对诊断" }).click();

  await expect(
    page.getByText("配对诊断已记录敏感访问：仅显示特征代码、通过结果、调整项与版本号。")
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "硬性条件结果" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "双向特征结果" })).toBeVisible();
  await expect(page.getByText(/阻断代码：/)).toBeVisible();
  await expect(page.getByText(/放宽代码：/)).toBeVisible();

  // Feature codes and versions are shown; profile content never is.
  for (const displayName of recommendationFixtureDisplayNames) {
    await expect(page.getByText(displayName)).toHaveCount(0);
  }
});
