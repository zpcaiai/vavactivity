import { expect, test } from "@playwright/test";

import {
  resetLoginRateLimits,
  seedAdminPlatformFixture,
  seedSuperAdmin,
  signInAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedAdminPlatformFixture();
  seedSuperAdmin();
});

test("administration platform exposes the governed dashboard", async ({ page }) => {
  await signInAdmin(page);
  await page.goto(`${adminBaseUrl}/admin/platform/dashboard`);
  await expect(page).toHaveURL(/admin\/platform\/dashboard$/u);
  await expect(page.getByRole("heading", { name: "统一管理运营平台" })).toBeVisible();
  await expect(page.getByText("NOT CERTIFIED")).toBeVisible();
});
