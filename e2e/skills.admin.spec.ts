import { execFileSync } from "node:child_process";

import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import { adminEmail, adminPassword, resetLoginRateLimits, seedSuperAdmin } from "./helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-m", "vav.cli.seed_permissions"], {
    stdio: "pipe"
  });
  seedSuperAdmin();
});

async function signIn(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/u);
}

test("Skill console exposes every governed view without sensitive payloads", async ({ page }) => {
  await signIn(page);
  for (const section of [
    "dashboard",
    "catalog",
    "installations",
    "executions",
    "dependencies",
    "permissions",
    "publishers",
    "reviews",
    "marketplace",
    "incidents",
    "audit"
  ]) {
    await page.goto(`${adminBaseUrl}/admin/skills/${section}`);
    await expect(page.getByRole("main").getByRole("heading", { name: "Skill 控制台" })).toBeVisible();
    await expect(page.locator("main")).not.toContainText(
      /input_encrypted|output_encrypted|configuration_encrypted|private_key|secret_value/iu
    );
  }
});

test("permission and Marketplace views retain visible release safeguards", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/skills/permissions`);
  await expect(page.getByText(/高风险权限不会隐藏/u)).toBeVisible();
  await page.goto(`${adminBaseUrl}/admin/skills/marketplace`);
  await expect(page.getByText(/签名、SBOM、兼容性和 Marketplace 人工审核/u)).toBeVisible();
});
