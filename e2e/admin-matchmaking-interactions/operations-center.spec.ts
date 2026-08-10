import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  recommendationFixtureDisplayNames,
  resetLoginRateLimits,
  seedMatchmakingInteractionFixture,
  seedSuperAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedMatchmakingInteractionFixture();
  seedSuperAdmin();
});

async function signIn(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/u);
}

test("the interaction center is redacted and states the fabrication boundary", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/matchmaking-interactions/pairs`);
  await expect(page.getByRole("heading", { name: "互动运营中心", level: 2 })).toBeVisible();
  await expect(page.getByText(/运营人员不能代替用户喜欢、接受、婉拒或同意交换联系方式/u))
    .toBeVisible();
  await expect(page.locator(".el-table")).toBeVisible();
  const body = await page.locator("body").innerText();
  for (const name of recommendationFixtureDisplayNames) expect(body).not.toContain(name);
  await expect(page.getByRole("button", { name: /创建喜欢|代替接受|同意交换/u }))
    .toHaveCount(0);
});

test("high-risk invalidation requires reason and purpose", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/matchmaking-interactions/pairs`);
  const invalidate = page.getByRole("button", { name: "失效" }).first();
  await expect(invalidate).toBeVisible();
  await invalidate.click();
  await expect(page.getByText("高风险操作必须填写原因和用途"))
    .toBeVisible();
});
