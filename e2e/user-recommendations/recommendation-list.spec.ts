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
  await page.getByLabel("邮箱或账号").fill(recommendationFixtureEmail("mei"));
  await page.getByLabel("密码").fill(recommendationFixturePassword);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/);
  await page.goto("/zh-CN/recommendations");
}

test("the daily list delivers frozen cards carrying reasons and information gaps", async ({
  page
}) => {
  await signInFixtureMember(page);

  await expect(page.getByRole("heading", { name: "今日推荐" })).toBeVisible();
  await expect(
    page.getByText("推荐只根据你自己填写的择偶条件和双方公开的档案资料生成。")
  ).toBeVisible();

  const cards = page.getByRole("article");
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThan(0);

  const firstCard = cards.first();
  // The reason text is produced by the backend from approved templates.
  await expect(firstCard.getByRole("heading", { name: "你们的共同点" })).toBeVisible();
  await expect(
    firstCard.getByText("推荐只是认识的机会，最终判断由你自己作出；平台不对结果作任何保证。")
  ).toBeVisible();

  // What the platform does not know is stated as a gap, never as a shortcoming.
  await expect(firstCard.getByRole("heading", { name: "尚未确认的信息" })).toBeVisible();
  await expect(
    firstCard.getByText("未填写的内容不会被推测，也不会被当作缺点。可以在进一步了解时自行确认。")
  ).toBeVisible();

  await expect(
    firstCard.getByText("浏览记录只用于控制曝光次数和推荐质量，对方不会收到你查看过的通知。")
  ).toBeVisible();
});

test("no card exposes a score, a percentage or the other member's opinion", async ({ page }) => {
  await signInFixtureMember(page);

  const firstCard = page.getByRole("article").first();
  await expect(firstCard).toBeVisible();
  await expect(
    firstCard.getByText(
      "平台不提供匹配分数或百分比，也不会展示对方对你的评价。是否继续了解，由你自己决定。"
    )
  ).toBeVisible();

  const cardText = await firstCard.innerText();
  expect(cardText).not.toMatch(/\d+\s*%/u);
  expect(cardText).not.toMatch(/\d+\s*分\b/u);
  expect(cardText).not.toMatch(/bps/iu);
  // The boundary statement is the only place these words are allowed to appear.
  const withoutBoundary = cardText.replace(
    "平台不提供匹配分数或百分比，也不会展示对方对你的评价。",
    ""
  );
  expect(withoutBoundary).not.toMatch(/匹配度|契合度|评分|得分|分数|排名|score/iu);

  // The rank position exists server-side and must never reach the member.
  await expect(page.getByText("对方对你的评分")).toHaveCount(0);
  await expect(firstCard.getByText(/第 \d+ 位/)).toHaveCount(0);
});

test("requesting the batch again returns the same batch instead of buying more", async ({
  page
}) => {
  await signInFixtureMember(page);

  await expect(
    page.getByText("重复获取只会返回同一批推荐，不会超出你设置的每日数量上限。")
  ).toBeVisible();

  const cards = page.getByRole("article");
  await expect(cards.first()).toBeVisible();
  const before = await cards.count();
  expect(before).toBeGreaterThan(0);
  await page.getByRole("button", { name: "获取今日推荐" }).click();
  await expect(page.getByRole("status")).toContainText(
    "重复请求不会超出每日数量上限。"
  );
  await expect(page.getByRole("status")).toContainText(/已获取每日推荐，共 \d+ 位。/);
  await expect(cards).toHaveCount(before);
});
