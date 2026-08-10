import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import { recommendationFixturePassword, resetLoginRateLimits, seedRelationshipFixture } from "../helpers";

let memberEmail = "";
test.beforeAll(() => {
  test.setTimeout(180_000);
  resetLoginRateLimits();
  memberEmail = seedRelationshipFixture();
});

async function signIn(page: Page) {
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱或账号").fill(memberEmail);
  await page.getByLabel("密码").fill(recommendationFixturePassword);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/u);
}

test("member sees a consent-preserving relationship journey", async ({ page }) => {
  await signIn(page);
  await page.goto("/zh-CN/account/relationships");
  await expect(page.getByRole("heading", { name: "关系旅程" })).toBeVisible();
  await expect(page.getByText(/阶段推进需要双方确认/)).toBeVisible();
  await page.locator(".card").first().click();
  await expect(page.getByRole("heading", { name: "双方确认阶段" })).toBeVisible();
  await expect(page.getByRole("button", { name: "结束关系旅程" })).toBeVisible();
  await expect(page.getByText(/关系打分|关系健康分/)).toHaveCount(0);
});
