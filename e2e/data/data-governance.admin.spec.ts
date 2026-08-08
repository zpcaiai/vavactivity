import { expect, test } from "@playwright/test";

import {
  resetLoginRateLimits,
  seedDataGovernanceFixture,
  seedSuperAdmin,
  signInAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedDataGovernanceFixture();
  seedSuperAdmin();
});

test.beforeEach(async ({ page }) => {
  await signInAdmin(page);
});

test("data steward can inspect contracts lineage and erasure status", async ({ page }) => {
  await page.goto(`${adminBaseUrl}/admin/data-governance/dashboard`);
  await expect(page.getByRole("heading", { name: "数据治理与完整性中心" })).toBeVisible();
  await expect(page.getByText("NOT CERTIFIED")).toBeVisible();
  await page.getByRole("link", { name: "数据血缘" }).click();
  await expect(page.getByRole("table")).toBeVisible();
  await page.getByRole("link", { name: "删除传播" }).click();
  await expect(page.getByRole("table")).toBeVisible();
});

test("data governance exposes no direct business-fact editor", async ({ page }) => {
  await page.goto(`${adminBaseUrl}/admin/data-governance/repairs`);
  await expect(page.getByText(/direct sql|mark paid|直接修改支付|伪造同意/i)).toHaveCount(0);
});
