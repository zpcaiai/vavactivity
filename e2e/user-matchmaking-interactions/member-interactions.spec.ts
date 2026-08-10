import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  recommendationFixturePassword,
  resetLoginRateLimits,
  seedMatchmakingInteractionFixture
} from "../helpers";

let senderEmail = "";

test.beforeAll(() => {
  resetLoginRateLimits();
  senderEmail = seedMatchmakingInteractionFixture();
});

async function signIn(page: Page) {
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱或账号").fill(senderEmail);
  await page.getByLabel("密码").fill(recommendationFixturePassword);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/u);
}

test("a member sees the mutual match and the separate pending invitation", async ({ page }) => {
  await signIn(page);
  await page.goto("/zh-CN/account/matchmaking/matches");
  await expect(page.getByRole("heading", { name: "互选与认识邀请" })).toBeVisible();
  await expect(page.getByText("单向喜欢、跳过原因和婉拒原因都保持私密。"))
    .toBeVisible();
  await expect(page.getByText("invitation_pending").first()).toBeVisible();

  await page.goto("/zh-CN/account/matchmaking/invitations");
  await expect(page.getByRole("link", { name: /(sender|recipient) · pending/u }).first())
    .toBeVisible();
});

test("member navigation exposes only outgoing choices, never incoming likes", async ({ page }) => {
  await signIn(page);
  await page.goto("/zh-CN/account/matchmaking/likes");
  await expect(page.getByRole("link", { name: "我的喜欢" })).toBeVisible();
  await expect(page.getByText(/收到的喜欢|谁喜欢了我/u)).toHaveCount(0);
  await expect(page.getByText(/单向喜欢、跳过原因和婉拒原因都保持私密/u)).toBeVisible();
});
