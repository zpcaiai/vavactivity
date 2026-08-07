import { expect, test } from "@playwright/test";

import {
  seedNotificationFixture,
  seedUserNotificationFixture,
  verifyUserFixture
} from "./helpers";

test.beforeAll(() => seedNotificationFixture());

test("a verified user reads, archives and configures persisted notifications", async ({ page }) => {
  const email = `notifications-e2e-${Date.now()}@example.com`;
  const password = "VavNotifications!2026_Secure#";
  await page.goto("/zh-CN/auth/register");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByLabel("我已阅读并同意服务条款与隐私说明").check();
  await page.getByRole("button", { name: "建立 VAV 账户" }).click();
  await expect(page.getByRole("status")).toContainText("请查收验证邮件");
  verifyUserFixture(email);
  seedUserNotificationFixture(email);

  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/);
  await expect(page.getByLabel("Notifications").getByText("1")).toBeVisible();

  await page.goto("/zh-CN/account/notifications");
  await expect(page.getByRole("heading", { name: "通知中心" })).toBeVisible();
  await expect(page.getByText("Batch 11 浏览器验收通知")).toBeVisible();
  await page.getByRole("button", { name: "全部标为已读" }).click();
  await expect(page.getByLabel("Notifications").getByText("1")).toHaveCount(0);
  await page.getByRole("button", { name: "归档" }).click();
  await expect(page.getByText("暂无通知")).toBeVisible();

  await page.goto("/zh-CN/account/notification-preferences");
  await expect(page.getByRole("heading", { name: "通知偏好" })).toBeVisible();
  await page.getByText("同意接收营销邮件").locator("input").check();
  await page.getByRole("button", { name: "保存偏好" }).click();
  await expect(page.getByRole("status")).toContainText("通知偏好已保存");
  await expect(page.getByText("不能完全关闭").first()).toBeVisible();
});
