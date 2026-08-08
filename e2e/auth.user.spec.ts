import { expect, test } from "@playwright/test";

import { verificationLinkFor } from "./helpers";

test("a user registers, verifies email, signs in and sees the current session", async ({
  page,
  request
}) => {
  const email = `e2e-user-${Date.now()}@example.com`;
  const password = "VavUser!2026_Secure#";

  await page.goto("/zh-CN/auth/register");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByLabel("我已阅读并同意服务条款与隐私说明").check();
  await page.getByRole("button", { name: "建立 VAV 账户" }).click();
  await expect(page.getByRole("status")).toContainText("请查收验证邮件");

  const verificationLink = await verificationLinkFor(request, email);
  await page.goto(verificationLink);
  await expect(page.getByRole("status")).toContainText("邮箱已验证");

  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/);
  await expect(page.getByRole("heading", { name: "我的账户" })).toBeVisible();

  await page.goto("/zh-CN/account/sessions");
  await expect(page.getByText("Web browser")).toBeVisible();
  await expect(page.getByText("当前设备")).toBeVisible();
});
