import { expect, test } from "@playwright/test";

import {
  seedDatingProfileFixture,
  seedProtectedDateOfBirth,
  verifyUserFixture
} from "../helpers";

test.beforeAll(() => seedDatingProfileFixture());

const password = "VavDating!2026_Secure#";

async function registerMember(page: import("@playwright/test").Page, email: string) {
  await page.goto("/zh-CN/auth/register");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByLabel("我已阅读并同意服务条款与隐私说明").check();
  await page.getByRole("button", { name: "建立 VAV 账户" }).click();
  verifyUserFixture(email);
  seedProtectedDateOfBirth(email);
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "欢迎回来" }).click();
}

test("an adult member creates a dating profile with strict privacy defaults", async ({ page }) => {
  const email = `dating-e2e-${Date.now()}@example.com`;
  await registerMember(page, email);

  await page.goto("/zh-CN/account/dating-profile");
  await expect(page.getByRole("heading", { name: "婚恋档案" })).toBeVisible();
  await expect(page.getByText("联系方式在任何场景下都不会自动公开")).toBeVisible();

  await page.getByRole("button", { name: "创建婚恋档案" }).click();
  await expect(page.getByRole("status")).toContainText("默认使用严格隐私模式");
  await expect(page.getByText("档案编号 VAV-")).toBeVisible();
});

test("the stepper exposes every profile section in order", async ({ page }) => {
  const email = `dating-steps-${Date.now()}@example.com`;
  await registerMember(page, email);
  await page.goto("/zh-CN/account/dating-profile");
  await page.getByRole("button", { name: "创建婚恋档案" }).click();

  for (const label of [
    "基本资料",
    "信仰",
    "婚史",
    "家庭",
    "生活方式",
    "自我介绍",
    "照片",
    "择偶条件",
    "隐私设置",
    "档案预览",
    "提交审核"
  ]) {
    await expect(page.getByRole("button", { name: label, exact: true })).toBeVisible();
  }
});

test("completeness is reported by the backend and never as a personal score", async ({ page }) => {
  const email = `dating-completeness-${Date.now()}@example.com`;
  await registerMember(page, email);
  await page.goto("/zh-CN/account/dating-profile");
  await page.getByRole("button", { name: "创建婚恋档案" }).click();
  await expect(page.getByText("仅衡量填写完成度")).toBeVisible();
  await expect(page.getByText(/还有 \d+ 个必填项/)).toBeVisible();
});

test("submission is blocked while required fields are missing", async ({ page }) => {
  const email = `dating-submit-${Date.now()}@example.com`;
  await registerMember(page, email);
  await page.goto("/zh-CN/account/dating-profile");
  await page.getByRole("button", { name: "创建婚恋档案" }).click();
  await page.getByRole("button", { name: "提交审核", exact: true }).click();
  await expect(page.getByText("还有必填项未完成")).toBeVisible();
  await expect(page.getByRole("button", { name: "提交审核" }).last()).toBeDisabled();
});
