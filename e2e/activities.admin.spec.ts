import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  resetLoginRateLimits,
  seedActivityFixture,
  seedSuperAdmin
} from "./helpers";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedActivityFixture();
  seedSuperAdmin();
});

test("an authorized operator can use the activity center", async ({ page }) => {
  await page.goto("http://localhost:5174/admin/login");
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  await page.goto("http://localhost:5174/admin/activities");
  await expect(page.getByRole("heading", { name: "活动中心", level: 2 })).toBeVisible();
  await expect(page.getByText("单向互选严格保密")).toBeVisible();
  await expect(page.getByText("activity-e2e-social")).toBeVisible();
  await page.getByRole("tab", { name: "活动后互选" }).click();
  await expect(page.getByText(/默认只展示聚合指标/)).toBeVisible();
  await page.getByRole("tab", { name: /候补/ }).click();
  await expect(page.getByText("原始顺序")).toBeVisible();
});
