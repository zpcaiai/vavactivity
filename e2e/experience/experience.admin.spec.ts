import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { adminEmail, adminPassword, resetLoginRateLimits, seedSuperAdmin } from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-m", "vav.cli.seed_permissions"]);
  execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-m", "vav.cli.seed_experience"]);
  seedSuperAdmin();
});

test("administrator can inspect every experience governance view", async ({ page }) => {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  for (const section of ["dashboard", "ia", "routes", "navigation", "tasks", "journeys", "handoffs", "search-governance", "help", "support", "dead-ends", "analytics", "evidence", "release", "audit"]) {
    await page.goto(`${adminBaseUrl}/admin/experience/${section}`);
    await expect(page.getByRole("heading", { name: "信息架构与体验闭环" })).toBeVisible();
  }
});
