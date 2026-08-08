import { expect, test } from "@playwright/test";

import { seedPrivacyFixture, verifyUserFixture } from "../helpers";

test.beforeAll(() => seedPrivacyFixture());

test("a user governs profile privacy consent export and AI memory", async ({ page }) => {
  const email = `privacy-e2e-${Date.now()}@example.com`;
  const password = "VavPrivacy!2026_Secure#";
  await page.goto("/zh-CN/auth/register");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByLabel("我已阅读并同意服务条款与隐私说明").check();
  await page.getByRole("button", { name: "建立 VAV 账户" }).click();
  await expect(page.getByRole("status")).toContainText("请查收验证邮件");
  verifyUserFixture(email);

  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/);

  await page.goto("/zh-CN/account/profile");
  await expect(page.getByRole("heading", { name: "隐私与数据中心" })).toBeVisible();
  await expect(page.getByText("联系方式独立加密保存")).toBeVisible();
  await page.getByLabel("显示名称").fill("Privacy E2E User");
  await page.getByRole("button", { name: "保存档案" }).click();
  await expect(page.getByRole("status")).toContainText("档案已保存");

  await page.goto("/zh-CN/account/privacy");
  await expect(page.getByLabel("隐私模式")).toHaveValue("strict");
  await expect(page.getByLabel("允许平台用户搜索")).toBeDisabled();

  await page.goto("/zh-CN/account/consents");
  await expect(page.getByText("external_model_training (zh-CN)")).toBeVisible();
  await expect(page.getByText("外部模型训练默认未授权")).toBeVisible();

  await page.goto("/zh-CN/account/privacy/requests");
  await page.getByRole("button", { name: "生成数据清单" }).click();
  await expect(page.getByText("数据清单已生成。")).toBeVisible();
  await expect(page.getByText("inventory")).toBeVisible();

  await page.goto("/zh-CN/account/ai-memory");
  await expect(page.getByText("长期记忆默认关闭")).toBeVisible();
  await expect(page.getByLabel("启用长期记忆（须先授予独立同意）")).not.toBeChecked();
});
