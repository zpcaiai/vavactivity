import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  seedPrivacyFixture,
  seedSuperAdmin
} from "../helpers";

test.beforeAll(() => {
  seedPrivacyFixture();
  seedSuperAdmin();
});

test("an authorized operator sees redacted governed privacy operations", async ({ page }) => {
  await page.goto("http://localhost:5174/admin/login");
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);

  await page.goto("http://localhost:5174/admin/privacy/dashboard");
  await expect(page.getByRole("heading", { name: "隐私运营中心", level: 2 })).toBeVisible();
  await expect(page.getByText("敏感字段值、导出令牌")).toBeVisible();
  await expect(page.getByLabel("隐私总览")).toBeVisible();

  await page.getByRole("tab", { name: "数据清单" }).click();
  await expect(page.getByText("identity.profile")).toBeVisible();
  await page.getByRole("tab", { name: "敏感分类" }).click();
  await expect(page.getByText("highly_restricted").first()).toBeVisible();
  await page.getByRole("tab", { name: "同意注册表" }).click();
  await expect(page.getByText("external_model_training")).toBeVisible();
  await page.getByRole("tab", { name: "保留策略" }).click();
  await expect(page.getByText("privacy.identity.profile")).toBeVisible();
  await expect(page.getByText("司法辖区法律文本")).toBeVisible();
});
