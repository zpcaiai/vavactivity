import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  seedCommerceFixture,
  seedSuperAdmin
} from "./helpers";

test.beforeAll(() => {
  seedCommerceFixture();
  seedSuperAdmin();
});

test("an authorized operator can inspect commerce and reconciliation surfaces", async ({
  page
}) => {
  await page.goto("http://localhost:5174/admin/login");
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);

  await page.goto("http://localhost:5174/admin/commerce/orders");
  await expect(page.getByRole("heading", { name: "订单", level: 2 })).toBeVisible();
  await expect(page.getByText("支付成功只来自已验签 Webhook")).toBeVisible();

  await page.goto("http://localhost:5174/admin/commerce/webhooks");
  await expect(page.getByRole("heading", { name: "Webhook", level: 2 })).toBeVisible();

  await page.goto("http://localhost:5174/admin/commerce/reconciliation");
  await page.getByRole("button", { name: "执行对账扫描" }).click();
  await expect(page.getByRole("heading", { name: "对账差异", level: 2 })).toBeVisible();
});
