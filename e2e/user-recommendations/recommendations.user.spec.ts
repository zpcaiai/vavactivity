import { expect, test } from "@playwright/test";

import {
  seedProtectedDateOfBirth,
  seedRecommendationFixture,
  verifyUserFixture
} from "../helpers";

test.beforeAll(() => seedRecommendationFixture());

const password = "VavDating!2026_Secure#";

async function signedInMember(page: import("@playwright/test").Page, prefix: string) {
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
  return email;
}

test("the recommendation page states that a match is an opportunity, not a promise", async ({
  page
}) => {
  await signedInMember(page, "rec-caveat");
  await page.goto("/zh-CN/account/recommendations");
  await expect(page.getByRole("heading", { name: "推荐" })).toBeVisible();
  await expect(
    page.getByText("推荐只是一个认识的机会，不代表平台对适配结果的保证。")
  ).toBeVisible();
});

test("an empty result is explained honestly instead of being padded", async ({ page }) => {
  await signedInMember(page, "rec-empty");
  await page.goto("/zh-CN/account/recommendations");
  await page.getByRole("button", { name: "获取今日推荐" }).click();
  // A member with no approved profile cannot receive candidates; the page must
  // say so plainly rather than invent anyone.
  await expect(
    page.getByText(/当前没有完全符合你全部硬性条件的推荐。|档案|资格/)
  ).toBeVisible();
});

test("the settings tab never offers a way around another member's rules", async ({ page }) => {
  await signedInMember(page, "rec-settings");
  await page.goto("/zh-CN/account/recommendations");
  await page.getByRole("button", { name: "推荐设置" }).click();
  await expect(page.getByText("任何设置都不会")).toBeVisible();
  await expect(page.getByText("突破对方的硬性条件")).toBeVisible();
  await expect(page.getByText("绕过安全限制")).toBeVisible();
  await expect(page.getByLabel("暂停推荐")).not.toBeChecked();
});

test("a member can pause recommendations and resume later", async ({ page }) => {
  await signedInMember(page, "rec-pause");
  await page.goto("/zh-CN/account/recommendations");
  await page.getByRole("button", { name: "推荐设置" }).click();
  await page.getByLabel("暂停推荐").check();
  await expect(page.getByText("推荐设置已更新。")).toBeVisible();
  await page.getByRole("button", { name: "今日推荐" }).click();
  await expect(page.getByText("你已暂停推荐。可以在「推荐设置」中随时恢复。")).toBeVisible();
});

test("transparency lists what is never used and what a member cannot see", async ({ page }) => {
  await signedInMember(page, "rec-transparency");
  await page.goto("/zh-CN/account/recommendations");
  await page.getByRole("button", { name: "推荐说明" }).click();
  await expect(page.getByText("永远不会被使用的信息")).toBeVisible();
  await expect(page.getByText("照片外貌评估")).toBeVisible();
  await expect(page.getByText("收入或消费能力")).toBeVisible();
  await expect(page.getByText("其他用户的择偶条件")).toBeVisible();
  await expect(page.getByText("其他用户对你的评分")).toBeVisible();
});

test("feedback personalisation can be switched off and learned tuning cleared", async ({
  page
}) => {
  await signedInMember(page, "rec-personalisation");
  await page.goto("/zh-CN/account/recommendations");
  await page.getByRole("button", { name: "推荐设置" }).click();
  await page.getByLabel("允许根据我的反馈微调推荐").uncheck();
  await expect(page.getByText("推荐设置已更新。")).toBeVisible();
  await page.getByRole("button", { name: "清除所有从反馈中学到的调整" }).click();
  await expect(page.getByText("已清除所有从反馈中学到的调整。")).toBeVisible();
});

test("relaxation is opt-in and off by default", async ({ page }) => {
  await signedInMember(page, "rec-relaxation");
  await page.goto("/zh-CN/account/recommendations");
  await page.getByRole("button", { name: "推荐设置" }).click();
  await expect(
    page.getByLabel("候选不足时，允许放宽我标记为「可放宽」的条件")
  ).not.toBeChecked();
});

test("the history tab shows the member their own recommendation record", async ({ page }) => {
  await signedInMember(page, "rec-history");
  await page.goto("/zh-CN/account/recommendations");
  await page.getByRole("button", { name: "推荐记录" }).click();
  await expect(page.getByText(/共 \d+ 条推荐记录。/)).toBeVisible();
});
