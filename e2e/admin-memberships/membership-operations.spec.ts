import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  resetLoginRateLimits,
  seedMembershipFixture,
  seedSuperAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";
test.beforeAll(() => { resetLoginRateLimits(); seedMembershipFixture(); seedSuperAdmin(); });

async function signIn(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/u);
}

test("membership operations cannot forge commerce authority", async ({ page }) => {
  await signIn(page);
  const plansResponsePromise = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/api/v1/admin/memberships/plans") &&
    response.request().method() === "GET" && response.ok()
  );
  await page.goto(`${adminBaseUrl}/admin/memberships/plans`);
  const plansPayload = await plansResponsePromise.then((response) => response.json()) as {
    data: Array<{ plan_code: string; plan_type: string; status: string }>;
  };
  expect(plansPayload.data.length).toBeGreaterThan(0);
  const freePlan = plansPayload.data.find((plan) => plan.plan_code === "free-v1");
  expect(freePlan).toBeTruthy();
  await expect(
    page.getByRole("main").getByRole("heading", { name: "会员运营中心" })
  ).toBeVisible();
  await expect(page.getByText(/不能伪造付款、覆盖使用量或授予安全绕过/)).toBeVisible();
  await expect(page.getByRole("cell", { name: "free-v1" })).toBeVisible();
  await expect(page.getByRole("cell", { name: freePlan!.plan_type, exact: true }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: freePlan!.status, exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /标记已支付|覆盖消费量|绕过安全/ })).toHaveCount(0);
});
