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
  await page.getByLabel("邮箱或账号").fill(recommendationFixtureEmail("daniel"));
  await page.getByLabel("密码").fill(recommendationFixturePassword);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/);
}

test("relaxing a condition is opt-in and never applied on the member's behalf", async ({
  page
}) => {
  await signInFixtureMember(page);
  await page.goto("/zh-CN/account/recommendation-preferences");

  await expect(page.getByRole("heading", { name: "推荐设置" })).toBeVisible();
  await expect(
    page.getByText(
      "这里的设置只影响你自己收到的推荐数量、节奏和范围，不会改变别人是否看到你，"
    )
  ).toBeVisible();

  await expect(page.getByLabel("接收扩展推荐（在我允许放宽的条件内）")).not.toBeChecked();
  await expect(
    page.getByText(
      "开启后，当完全符合条件的人选不足时，系统可以在下方勾选的条件上适度放宽，并在推荐中明确标注。"
    )
  ).toBeVisible();
  await expect(
    page.getByText("未勾选的条件永远不会被系统放宽。安全相关的限制不受此设置影响。")
  ).toBeVisible();
  await expect(page.getByLabel("年龄范围")).not.toBeChecked();
});

test("opting in is saved for the next batch and can be withdrawn again", async ({ page }) => {
  await signInFixtureMember(page);
  await page.goto("/zh-CN/account/recommendation-preferences");

  await page.getByLabel("接收扩展推荐（在我允许放宽的条件内）").check();
  await page.getByLabel("所在城市").check();
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByRole("status")).toContainText(
    "推荐设置已保存，将从下一批推荐开始生效。"
  );

  await page.reload();
  await expect(page.getByLabel("接收扩展推荐（在我允许放宽的条件内）")).toBeChecked();
  await expect(page.getByLabel("所在城市")).toBeChecked();

  // Withdrawing the permission is a single click and takes effect immediately.
  await page.getByLabel("所在城市").uncheck();
  await page.getByLabel("接收扩展推荐（在我允许放宽的条件内）").uncheck();
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByRole("status")).toContainText(
    "推荐设置已保存，将从下一批推荐开始生效。"
  );
  await page.reload();
  await expect(page.getByLabel("接收扩展推荐（在我允许放宽的条件内）")).not.toBeChecked();
  await expect(page.getByLabel("所在城市")).not.toBeChecked();
});

test("a relaxed recommendation always discloses which condition was relaxed", async ({
  page
}) => {
  await signInFixtureMember(page);
  await page.goto("/zh-CN/recommendations");
  await expect(page.getByRole("heading", { name: "今日推荐" })).toBeVisible();

  // The notice only renders for an item the engine actually relaxed, and when it
  // does it must name the conditions and link back to the member's own setting.
  const notices = page.getByRole("heading", { name: "这条推荐放宽了你允许放宽的条件" });
  await expect(
    page.getByText(
      "只有你在推荐设置中标记为“可放宽”的条件才会被放宽；标记为必须满足的条件永远不会被跳过。"
    )
  ).toHaveCount(await notices.count());
  await expect(page.getByRole("link", { name: "调整可放宽的条件" })).toHaveCount(
    await notices.count()
  );
});
