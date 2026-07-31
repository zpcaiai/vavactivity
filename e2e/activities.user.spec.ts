import { expect, test } from "@playwright/test";

import { seedActivityFixture, verificationLinkFor } from "./helpers";

test.beforeAll(() => seedActivityFixture());

test("a verified user registers for a free activity through the entitlement pipeline", async ({
  page,
  request
}) => {
  const email = `activity-e2e-${Date.now()}@example.com`;
  const password = "VavActivity!2026_Secure#";
  await page.goto("/zh-CN/auth/register");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByLabel("我已阅读并同意服务条款与隐私说明").check();
  await page.getByRole("button", { name: "建立 VAV 账户" }).click();
  await page.goto(await verificationLinkFor(request, email));
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/account\/security$/);

  await page.goto("/zh-CN/activities/city-connections-evening");
  await page.getByLabel("你对活动有什么期待？").fill("认识认真同行的人");
  await page.getByLabel("我同意活动守则与隐私边界").check();
  await page.getByRole("button", { name: "提交报名" }).click();
  await expect(page.getByText(/confirmed/)).toBeVisible();

  await page.goto("/zh-CN/account/activity-registrations");
  await expect(page.getByText("confirmed · not_checked_in", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "生成短时签到码" })).toBeVisible();
  await page.getByRole("link", { name: "活动通行、分组与活动后互选" }).click();
  await expect(page.getByRole("heading", { name: "城市同行交流夜", level: 1 })).toBeVisible();
  await expect(page.getByText(/浦东新区示例路 100 号/)).toBeVisible();
  await expect(page.getByText("仅使用你在这里明确授权的展示资料，不读取报名答案。")).toBeVisible();
});

test("activity discovery and authoritative ticket availability support English", async ({ page }) => {
  await page.goto("/en/activities/city-connections-evening");
  await expect(page.getByRole("heading", { name: "City Connections Evening", level: 1 })).toBeVisible();
  await expect(page.getByRole("button", { name: "Submit registration" })).toBeVisible();
  await expect(page.locator("option").filter({ hasText: /Free · available/ })).toHaveCount(1);
});
