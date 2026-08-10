import { execFileSync } from "node:child_process";

import { expect, test, type Page } from "@playwright/test";

import { adminEmail, adminPassword, resetLoginRateLimits, seedSuperAdmin } from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-m", "vav.cli.seed_permissions"], {
    stdio: "pipe"
  });
  execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-m", "vav.cli.seed_quality"], {
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

test("quality console exposes every permission-gated operational view", async ({ page }) => {
  await signIn(page);
  for (const section of [
    "dashboard",
    "requirements",
    "capabilities",
    "traceability",
    "business-flows",
    "gaps",
    "risks",
    "waivers",
    "evidence",
    "gates",
    "gate-runs",
    "releases",
    "certifications",
    "audit"
  ]) {
    await page.goto(`${adminBaseUrl}/admin/quality/${section}`);
    await expect(page.getByRole("heading", { name: "质量治理与发布门禁" })).toBeVisible();
    await expect(page.locator("main")).not.toContainText(
      /artifact_reference_encrypted.*(?:s3|https)|password|private_key|secret_value/iu
    );
  }
});

test("dashboard keeps production fail-closed policy visible", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/quality/dashboard`);
  await expect(page.getByText("FAIL CLOSED")).toBeVisible();
  await expect(page.getByText(/生产环境不接受 Conditional Go/u)).toBeVisible();
});
