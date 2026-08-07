import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  seedNotificationFixture,
  seedSuperAdmin
} from "./helpers";

test.beforeAll(() => {
  seedNotificationFixture();
  seedSuperAdmin();
});

test("an authorized operator inspects governed notification operations", async ({ page }) => {
  await page.goto("http://localhost:5174/admin/login");
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);

  await page.goto("http://localhost:5174/admin/notifications/dashboard");
  await expect(page.getByRole("heading", { name: "通知运营中心", level: 2 })).toBeVisible();
  await expect(page.getByText("默认不展示完整邮件正文")).toBeVisible();
  await expect(page.getByText("Provider：mailpit")).toBeVisible();

  await page.getByRole("tab", { name: "模板中心" }).click();
  await expect(page.getByLabel("模板中心").getByText("password-changed")).toBeVisible();
  await expect(page.getByLabel("模板中心").getByText("激活后不可原地修改")).toBeVisible();
  await page.getByRole("tab", { name: "事件订阅" }).click();
  await expect(page.getByLabel("事件订阅").getByText("auth.password.changed")).toBeVisible();
  await page.getByRole("tab", { name: "Campaign" }).click();
  await expect(page.getByLabel("Campaign").getByText("创建者不能自行批准正式群发")).toBeVisible();
  await page.getByRole("tab", { name: "Provider 与抑制" }).click();
  await expect(page.getByLabel("Provider 与抑制").getByText("Provider Event")).toBeVisible();
});
