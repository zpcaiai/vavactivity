import { expect, test } from "@playwright/test";

import { seedAiFixture, verifyUserFixture } from "./helpers";

test.beforeAll(() => seedAiFixture());

test("a verified user accepts separate consent and receives a governed AI turn", async ({
  page
}) => {
  const email = `ai-e2e-${Date.now()}@example.com`;
  const password = "VavAiAssistant!2026_Secure#";
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

  await page.goto("/zh-CN/ai-assistant");
  await expect(page.getByRole("heading", { name: "Hanna 关系助理" })).toBeVisible();
  await expect(page.getByText("不是紧急、医疗、法律或持牌辅导服务")).toBeVisible();
  await page.getByLabel("我已理解并选择开始 AI 对话").check();
  await page.getByLabel(/允许本对话使用可选长期记忆/).check();
  await page.getByRole("button", { name: "开始对话" }).click();
  await page.getByPlaceholder(/描述一次具体互动/).fill("平台现在有哪些课程？");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("当前可核对的服务")).toBeVisible();
  await expect(page.getByText(/granted/)).toBeVisible();
  await page.getByRole("button", { name: "保存为行动项" }).click();
  await page.getByRole("button", { name: "确认保存" }).click();
  await expect(page.getByRole("status")).toContainText("确认保存");

  await page.getByPlaceholder(/描述一次具体互动/).fill("他正在追我，我现在有危险。");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("普通建议已暂停")).toBeVisible();
  await expect(page.getByText("系统已创建受限的人工复核")).toBeVisible();
});
