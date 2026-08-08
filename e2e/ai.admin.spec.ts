import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  resetLoginRateLimits,
  seedAiFixture,
  seedSuperAdmin
} from "./helpers";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedAiFixture();
  seedSuperAdmin();
});

test("an authorized operator inspects AI registries, safety referrals and evaluation evidence", async ({
  page
}) => {
  await page.goto("http://localhost:5174/admin/login");
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  await page.goto("http://localhost:5174/admin/ai");
  await expect(page.getByRole("heading", { name: "AI 运营与安全中心" })).toBeVisible();
  await expect(page.getByText("默认只显示匿名摘要")).toBeVisible();

  await page.getByRole("tab", { name: "安全转介" }).click();
  await expect(page.getByText(/AIR-/).first()).toBeVisible();
  await page.getByRole("tab", { name: "Prompt 发布" }).click();
  await expect(page.getByText("hanna-core")).toBeVisible();
  await page.getByRole("tab", { name: "受控工具" }).click();
  await expect(page.getByText("create_counseling_referral")).toBeVisible();
  await expect(page.getByText("不允许创建任意代码 Tool")).toBeVisible();
  await page.getByRole("tab", { name: "评测与审计" }).click();
  await expect(page.getByText("passed").first()).toBeVisible();
});
