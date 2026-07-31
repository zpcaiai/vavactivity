import { expect, test } from "@playwright/test";

import { adminEmail, adminPassword, seedSuperAdmin } from "./helpers";

test.beforeAll(() => {
  seedSuperAdmin();
});

test("an administrator signs in and reaches permission-protected operations", async ({
  page
}) => {
  await page.goto("http://localhost:5174/admin/login");
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();

  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  await expect(page.getByRole("heading", { name: "工作台" })).toBeVisible();
  await page.goto("http://localhost:5174/admin/access/roles");
  await expect(page.getByRole("heading", { name: "角色权限" })).toBeVisible();

  await page.getByTestId("admin-locale-select").click();
  await page.getByRole("option", { name: "English" }).click();
  await expect(page.getByText("Operations workspace")).toBeVisible();
});
