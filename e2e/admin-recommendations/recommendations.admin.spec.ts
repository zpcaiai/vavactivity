import { expect, test } from "@playwright/test";

import { adminEmail, adminPassword, seedRecommendationFixture, seedSuperAdmin } from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  seedSuperAdmin();
  seedRecommendationFixture();
});

async function signIn(page: import("@playwright/test").Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "登录运营后台" }).click();
  await expect(page).toHaveURL(/\/admin(\/|$)/);
}

test("the operations centre states that a strategy needs evaluation and approval", async ({
  page
}) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/dashboard`);
  await expect(page.getByRole("heading", { name: "推荐运营中心" })).toBeVisible();
  await expect(
    page.getByText(/策略必须先通过评估与审批才能上线/)
  ).toBeVisible();
  await expect(page.getByText(/不能绕过用户的硬性条件与安全限制/)).toBeVisible();
});

test("every operations section is reachable", async ({ page }) => {
  await signIn(page);
  for (const [path, label] of [
    ["dashboard", "推荐总览"],
    ["strategies", "策略版本"],
    ["features", "特征清单"],
    ["constraints", "硬性条件"],
    ["batches", "推荐批次"],
    ["exposures", "曝光统计"],
    ["feedback", "反馈统计"],
    ["evaluations", "离线评估"],
    ["experiments", "实验管理"],
    ["diagnostics", "用户诊断"],
    ["audit", "推荐审计"]
  ] as const) {
    await page.goto(`${adminBaseUrl}/admin/recommendations/${path}`);
    await expect(page.getByRole("link", { name: label })).toBeVisible();
  }
});

test("the dashboard reports safety guardrails, not engagement", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/dashboard`);
  await expect(page.getByRole("heading", { name: "安全护栏" })).toBeVisible();
  await expect(page.getByText("点击率")).toHaveCount(0);
});

test("user diagnostics are aggregate only and name no candidate", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/diagnostics`);
  await expect(
    page.getByText("诊断只返回聚合口径的排除原因，不会展示任何一位候选人的档案内容。")
  ).toBeVisible();
});

test("the active strategy and its version are visible to operators", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/recommendations/strategies`);
  await expect(page.getByText("baseline-bidirectional")).toBeVisible();
});
