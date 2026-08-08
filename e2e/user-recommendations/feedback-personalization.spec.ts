import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  recommendationFixtureEmail,
  recommendationFixturePassword,
  resetLoginRateLimits,
  seedRecommendationFixture
} from "../helpers";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedRecommendationFixture();
});

const personalizationLabel = "允许根据我的浏览与反馈调整推荐";

async function openPreferences(page: Page) {
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱或账号").fill(recommendationFixtureEmail("mei"));
  await page.getByLabel("密码").fill(recommendationFixturePassword);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/);
  await page.goto("/zh-CN/account/recommendation-preferences");
  await expect(page.getByRole("heading", { name: "推荐设置" })).toBeVisible();
}

test("behavioural personalization can be switched off and the switch is visible to the member", async ({
  page
}) => {
  await openPreferences(page);
  await expect(
    page.getByText("关闭后，推荐只使用你明确填写的条件。已经学习到的调整可以用下方按钮清除。")
  ).toBeVisible();

  await page.getByLabel(personalizationLabel).check();
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByRole("status")).toContainText(
    "推荐设置已保存，将从下一批推荐开始生效。"
  );
  await page.goto("/zh-CN/account/recommendation-transparency");
  await expect(page.getByText("当前状态：已开启")).toBeVisible();

  await page.goto("/zh-CN/account/recommendation-preferences");
  await page.getByLabel(personalizationLabel).uncheck();
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByRole("status")).toContainText(
    "推荐设置已保存，将从下一批推荐开始生效。"
  );
  await page.reload();
  await expect(page.getByLabel(personalizationLabel)).not.toBeChecked();

  await page.goto("/zh-CN/account/recommendation-transparency");
  await expect(page.getByText("当前状态：已关闭")).toBeVisible();

  // Leave the account in the platform default state for the next run.
  await page.goto("/zh-CN/account/recommendation-preferences");
  await page.getByLabel(personalizationLabel).check();
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByRole("status")).toContainText(
    "推荐设置已保存，将从下一批推荐开始生效。"
  );
});

test("everything the engine learned from behaviour can be cleared", async ({ page }) => {
  await openPreferences(page);

  await expect(page.getByText(/当前已根据行为调整 \d+ 项。/)).toBeVisible();
  await page.getByRole("button", { name: "重置个性化调整" }).click();
  await expect(page.getByRole("status")).toContainText(
    /已清除 \d+ 项根据行为学习到的调整，恢复为平台默认设置。/
  );
  await expect(page.getByText("当前已根据行为调整 0 项。")).toBeVisible();
});
