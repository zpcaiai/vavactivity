import { expect, test } from "@playwright/test";

import { seedCounselingFixture, verificationLinkFor } from "./helpers";

test.beforeAll(() => seedCounselingFixture());

test("a verified user can hold a slot and create a private counseling appointment", async ({
  page,
  request
}) => {
  const email = `counseling-e2e-${Date.now()}@example.com`;
  const password = "VavCounseling!2026_Secure#";
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

  await page.goto("/zh-CN/counseling/growth-support-session");
  await expect(page.getByRole("heading", { name: "关系成长支持会谈", level: 1 })).toBeVisible();
  await expect(page.getByTestId("counseling-scope-notice")).toContainText("不替代");
  await page.getByRole("link", { name: "选择预约时间" }).click();
  await page.locator('input[name="slot"]').first().check();
  await page.getByLabel("本次希望讨论的目标").fill("练习清晰沟通和尊重边界");
  await page.getByRole("button", { name: "确认预约" }).click();
  await expect(page).toHaveURL(/\/account\/counseling\//);
  await expect(page.getByText("状态：confirmed")).toBeVisible();
  await expect(page.getByText("录音与转写默认关闭")).toBeVisible();
});
