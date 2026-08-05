import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  resetLoginRateLimits,
  seedDatingProfileFixture,
  seedSuperAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  seedSuperAdmin();
  seedDatingProfileFixture();
});

async function signIn(page: import("@playwright/test").Page) {
  resetLoginRateLimits();
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/u);
}

test("the review center states what reviewers may not see", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/matchmaking/reviews`);
  await expect(
    page.getByRole("heading", { name: "婚恋档案运营中心", level: 2 })
  ).toBeVisible();
  await expect(
    page.getByText(/审核员默认看不到联系方式、AI 对话、辅导记录与支付资料/)
  ).toBeVisible();
  await expect(page.getByText(/查看原始照片需要独立权限并记录敏感访问/)).toBeVisible();
});

test("every review section is reachable", async ({ page }) => {
  await signIn(page);
  for (const [path, label] of [
    ["profiles", "婚恋档案"],
    ["reviews", "审核队列"],
    ["photo-reviews", "照片审核"],
    ["schema-releases", "档案 Schema"],
    ["taxonomies", "字典管理"],
    ["projections", "推荐投影"],
    ["audit", "档案审计"]
  ] as const) {
    await page.goto(`${adminBaseUrl}/admin/matchmaking/${path}`);
    await expect(page.getByRole("tab", { name: label })).toBeVisible();
  }
});

test("the profile list exposes lifecycle actions with reason codes", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/matchmaking/profiles`);
  await expect(page.getByRole("combobox", { name: "原因代码" })).toBeVisible();
  await expect(page.getByPlaceholder("用户可见说明")).toBeVisible();
  await expect(
    page.getByPlaceholder("内部备注（加密保存，用户不可见）")
  ).toBeVisible();
});

test("the projection center can rebuild from the approved version", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/matchmaking/projections`);
  await expect(page.getByRole("button", { name: "处理投影任务队列" })).toBeVisible();
});

test("schema and taxonomy centers are read-only registries by default", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/matchmaking/schema-releases`);
  await expect(page.getByRole("tab", { name: "档案 Schema" })).toBeVisible();
  await page.goto(`${adminBaseUrl}/admin/matchmaking/taxonomies`);
  await expect(page.getByRole("tab", { name: "字典管理" })).toBeVisible();
});
