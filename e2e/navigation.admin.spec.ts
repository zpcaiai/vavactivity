import { expect, test } from "@playwright/test";

import { adminEmail, adminPassword, seedSuperAdmin } from "./helpers";

test.beforeAll(() => {
  seedSuperAdmin();
});

test("an editor updates localized navigation and the public API reflects it", async ({
  page,
  request
}) => {
  const label = `首页 ${Date.now()}`;

  await page.goto("http://localhost:5174/admin/login");
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);

  await page.goto("http://localhost:5174/admin/content/navigation");
  await expect(page.getByRole("heading", { name: "导航管理", level: 2 })).toBeVisible();
  const firstItem = page.locator(".navigation-item-card").first();
  await firstItem.getByLabel("简体中文").fill(label);
  await page.getByRole("button", { name: "保存导航" }).click();
  await expect(page.getByText("导航已保存并刷新公共缓存。")).toBeVisible();

  const response = await request.get(
    "http://localhost:8000/api/v1/public/navigation/main_navigation?locale=zh-CN"
  );
  expect(response.ok()).toBeTruthy();
  const payload = await response.json() as {
    data: { items: Array<{ label: string }> };
  };
  expect(payload.data.items[0]?.label).toBe(label);
});
