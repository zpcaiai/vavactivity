import { expect, test } from "@playwright/test";

import {
  resetLoginRateLimits,
  seedDatingProfileFixture,
  seedProtectedDateOfBirth,
  verifyUserFixture
} from "../helpers";

test.beforeAll(() => seedDatingProfileFixture());

const password = "VavDating!2026_Secure#";

async function memberWithProfile(page: import("@playwright/test").Page, prefix: string) {
  resetLoginRateLimits();
  const email = `${prefix}-${Date.now()}@example.com`;
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
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/u);
  await page.goto("/zh-CN/account/dating-profile");
  await page.getByRole("button", { name: "创建婚恋档案" }).click();
  return email;
}

test("photo guidance states EXIF removal and that no biometric template is built", async ({
  page
}) => {
  await memberWithProfile(page, "dating-photos");
  await page.getByRole("button", { name: "照片", exact: true }).click();
  await expect(page.getByText("自动清除 EXIF")).toBeVisible();
  await expect(page.getByText("平台不进行人脸识别，也不建立生物特征模板。")).toBeVisible();
});

test("hard partner criteria are labelled as exclusions and are never auto-relaxed", async ({
  page
}) => {
  await memberWithProfile(page, "dating-preferences");
  await page.getByRole("button", { name: "择偶条件", exact: true }).click();
  await expect(page.getByText("会直接排除不符合的候选人")).toBeVisible();
  await expect(page.getByText("也不会从你的叙述文字中推断隐藏偏好")).toBeVisible();
  await expect(
    page.getByLabel("允许系统在候选人不足时适度放宽非硬性条件")
  ).not.toBeChecked();
});

test("field privacy is described as a backend decision", async ({ page }) => {
  await memberWithProfile(page, "dating-privacy");
  await page.getByRole("button", { name: "隐私设置", exact: true }).click();
  await expect(page.getByText("由后端在每次查询时判定")).toBeVisible();
  await expect(page.getByText("联系方式在任何场景都不会自动公开")).toBeVisible();
});

test("preview shows a different field set per viewing context", async ({ page }) => {
  await memberWithProfile(page, "dating-preview");
  await page.getByRole("button", { name: "档案预览", exact: true }).click();
  await page.getByLabel("查看场景").selectOption("recommendation_card");
  await expect(page.getByText(/联系方式：\s*不可见/)).toBeVisible();
  await page.getByLabel("查看场景").selectOption("mutual_match");
  await expect(page.getByText(/联系方式：\s*不可见/)).toBeVisible();
});

test("narratives warn against contact details", async ({ page }) => {
  await memberWithProfile(page, "dating-narratives");
  await page.getByRole("button", { name: "自我介绍", exact: true }).click();
  await expect(
    page.getByText("请勿在文字中填写电话、邮箱、微信或站外链接，这类内容会被拒绝。")
  ).toBeVisible();
});
