import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import { adminEmail, adminPassword, resetLoginRateLimits, seedSuperAdmin } from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";
test.beforeAll(() => { resetLoginRateLimits(); seedSuperAdmin(); });

async function signIn(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
}

test("authorized operators can reach every least-privilege queue", async ({ page }) => {
  await signIn(page);
  for (const section of ["reports", "cases", "moderation", "harassment", "fraud", "restrictions", "appeals", "rules", "red-team", "audit"]) {
    await page.goto(`${adminBaseUrl}/admin/trust-safety/${section}`);
    await expect(
      page.getByRole("main").getByRole("heading", { name: "信任与安全中心" })
    ).toBeVisible();
    await expect(page.getByText(/自动信号只能冻结、限速或升级复核/)).toBeVisible();
  }
});

test("red-team view retains fail-closed certification language", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/trust-safety/red-team`);
  await expect(page.getByText(/屏蔽绕过率必须为 0/)).toBeVisible();
  await expect(page.getByText(/NOT_CERTIFIED/)).toBeVisible();
});
