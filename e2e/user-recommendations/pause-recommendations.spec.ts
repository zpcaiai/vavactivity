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

async function signInFixtureMember(page: Page) {
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱或账号").fill(recommendationFixtureEmail("peter"));
  await page.getByLabel("密码").fill(recommendationFixturePassword);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/);
}

async function setPaused(page: Page, paused: boolean) {
  await page.goto("/zh-CN/account/recommendation-preferences");
  await expect(page.getByRole("heading", { name: "推荐设置" })).toBeVisible();
  const toggle = page.getByLabel("暂停接收推荐");
  if (paused) {
    await toggle.check();
  } else {
    await toggle.uncheck();
  }
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByRole("status")).toContainText(
    "推荐设置已保存，将从下一批推荐开始生效。"
  );
}

test("pausing stops delivery and resuming brings it back", async ({ page }) => {
  await signInFixtureMember(page);

  await page.goto("/zh-CN/recommendations");
  await expect(page.getByRole("button", { name: "获取今日推荐" })).toBeEnabled();

  await setPaused(page, true);
  await page.goto("/zh-CN/recommendations");
  await expect(
    page.getByText("你已暂停接收推荐，恢复后才会生成新的批次。")
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "获取今日推荐" })).toBeDisabled();

  await setPaused(page, false);
  await page.goto("/zh-CN/recommendations");
  await expect(page.getByText("你已暂停接收推荐，恢复后才会生成新的批次。")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "获取今日推荐" })).toBeEnabled();
});

test("the pause control states that it also removes the member from new lists", async ({
  page
}) => {
  await signInFixtureMember(page);
  await page.goto("/zh-CN/account/recommendation-preferences");

  await expect(page.getByLabel("暂停接收推荐")).not.toBeChecked();
  await expect(
    page.getByText(
      "暂停后不会生成新的批次，你的档案也不会出现在他人的新推荐中。随时可以恢复。"
    )
  ).toBeVisible();
  await expect(page.getByText("设置为 0 表示不再接收新的推荐。")).toBeVisible();
});
