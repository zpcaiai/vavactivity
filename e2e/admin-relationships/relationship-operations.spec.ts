import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import { adminEmail, adminPassword, resetLoginRateLimits, seedRelationshipFixture, seedSuperAdmin } from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";
test.beforeAll(() => { resetLoginRateLimits(); seedRelationshipFixture(); seedSuperAdmin(); });

async function signIn(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/u);
}

test("operations view is redacted and cannot make member decisions", async ({ page }) => {
  await signIn(page);
  const journeysResponsePromise = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/api/v1/admin/relationships") &&
    response.request().method() === "GET" && response.ok()
  );
  await page.goto(`${adminBaseUrl}/admin/relationships/journeys`);
  const journeysPayload = await journeysResponsePromise.then((response) => response.json()) as {
    data: Array<{ journey_number: string; status: string; current_stage_code: string }>;
  };
  expect(journeysPayload.data.length).toBeGreaterThan(0);
  const journey = journeysPayload.data[0];
  await expect(
    page.getByRole("main").getByRole("heading", { name: "关系运营中心" })
  ).toBeVisible();
  await expect(page.getByText(/不能代替成员确认阶段/)).toBeVisible();
  await expect(page.getByRole("cell", { name: journey.journey_number })).toBeVisible();
  await expect(page.getByRole("cell", { name: journey.status, exact: true }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: journey.current_stage_code, exact: true }).first()).toBeVisible();
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /确认阶段|恢复已结束|同意恢复/ })).toHaveCount(0);
});
