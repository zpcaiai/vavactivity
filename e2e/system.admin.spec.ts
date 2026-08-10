import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import { adminEmail, adminPassword, resetLoginRateLimits, seedSuperAdmin } from "./helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedSuperAdmin();
});

async function signIn(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/u);
}

test("an authorized operator sees redacted production status and every governed view", async ({ page }) => {
  await signIn(page);
  for (const section of [
    "status",
    "releases",
    "jobs",
    "integrations",
    "dead-letters",
    "feature-flags",
    "maintenance",
    "backups",
    "restore-drills",
    "capacity"
  ]) {
    await page.goto(`${adminBaseUrl}/admin/system/${section}`);
    await expect(page.getByRole("main").getByRole("heading", { name: "系统运维中心" })).toBeVisible();
    await expect(page.getByText(/仅展示脱敏运行信息/u)).toBeVisible();
    await expect(page.locator("main")).not.toContainText(/password|secret_value|private_key/iu);
  }
});

test("feature flag UI documents four-eyes activation and protected controls", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/system/feature-flags`);
  await expect(page.getByText(/创建人不能自我审批|需要另一位管理员审批/u).first()).toBeVisible();
  await expect(page.getByText(/安全、隐私、支付、授权及加密/u)).toBeVisible();
});
