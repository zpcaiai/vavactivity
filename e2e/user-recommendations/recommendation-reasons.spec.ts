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

async function openFirstRecommendation(page: Page) {
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱或账号").fill(recommendationFixtureEmail("grace"));
  await page.getByLabel("密码").fill(recommendationFixturePassword);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/);
  await page.goto("/zh-CN/recommendations");
  await page.getByRole("button", { name: "查看完整推荐" }).first().click();
  await expect(page.getByRole("heading", { name: "推荐详情" })).toBeVisible();
}

test("every reason is an approved sentence without a number, a claim or a promise", async ({
  page
}) => {
  await openFirstRecommendation(page);

  const card = page.getByRole("article").first();
  // The backend picks one of the two approved summaries for the whole card.
  await expect(
    card.getByText(
      /你们在以下方面较为接近，也有一些信息仍需进一步了解。|这位成员符合你设置的基本条件，你们的资料还需要进一步补充。/
    )
  ).toBeVisible();

  const reasons = await card.getByRole("listitem").allInnerTexts();
  expect(reasons.length).toBeGreaterThan(0);
  for (const reason of reasons) {
    expect(reason).not.toMatch(/\d+\s*%/u);
    expect(reason).not.toMatch(/bps/iu);
    expect(reason).not.toMatch(/一定|保证|必然|绝配|最合适|成功率/u);
  }

  await expect(
    card.getByText("推荐只是认识的机会，最终判断由你自己作出；平台不对结果作任何保证。")
  ).toBeVisible();
});

test("a gap is stated as missing information and never guessed at", async ({ page }) => {
  await openFirstRecommendation(page);

  const card = page.getByRole("article").first();
  const gaps = card.getByRole("heading", { name: "尚未确认的信息" });
  await expect(gaps).toBeVisible();
  await expect(
    card.getByText("未填写的内容不会被推测，也不会被当作缺点。可以在进一步了解时自行确认。")
  ).toHaveCount(await gaps.count());
});

test("the 不合适 dialog keeps the reason private and refuses to submit without one", async ({
  page
}) => {
  await openFirstRecommendation(page);

  await page.getByRole("article").first().getByRole("button", { name: "不合适" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "这条推荐不合适" })).toBeVisible();
  await expect(
    dialog.getByText(
      "你的反馈只用于调整你自己收到的推荐，对方不会收到任何通知，也看不到反馈内容。"
    )
  ).toBeVisible();

  // A reason is required, and the free-text box warns against contact details.
  await expect(dialog.getByRole("button", { name: "提交反馈" })).toBeDisabled();
  await expect(dialog.getByPlaceholder("请勿填写联系方式或对他人的评价。")).toBeVisible();
  await expect(dialog.getByLabel("信仰期待不同")).not.toBeChecked();
  await dialog.getByLabel("信仰期待不同").check();
  await expect(dialog.getByRole("button", { name: "提交反馈" })).toBeEnabled();

  await dialog.getByRole("button", { name: "取消" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
