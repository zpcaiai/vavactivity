import { expect, test } from "@playwright/test";

import {
  resetLoginRateLimits,
  seedProcessGovernanceFixture,
  seedSuperAdmin,
  signInAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedProcessGovernanceFixture();
  seedSuperAdmin();
});

test.beforeEach(async ({ page }) => {
  await signInAdmin(page);
});

test("process operator can inspect governed instances and recovery controls", async ({ page }) => {
  await page.goto(`${adminBaseUrl}/admin/processes/dashboard`);
  await expect(page.getByRole("heading", { name: "业务流程与 Saga 控制中心" })).toBeVisible();
  await expect(page.getByText("NOT CERTIFIED")).toBeVisible();
  await page.getByRole("link", { name: "状态机" }).click();
  await expect(page.getByRole("button", { name: "运行状态机验证" })).toBeVisible();
  await page.getByRole("link", { name: "卡死检测" }).click();
  await expect(page.getByRole("button", { name: "扫描卡死流程" })).toBeVisible();
});

test("process console exposes no direct domain-state editor", async ({ page }) => {
  await page.goto(`${adminBaseUrl}/admin/processes/interventions`);
  await expect(page.getByText(/direct sql|直接修改状态|伪造支付/i)).toHaveCount(0);
});
