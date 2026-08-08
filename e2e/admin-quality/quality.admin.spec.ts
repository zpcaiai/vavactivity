import { expect, test, type Page } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  resetLoginRateLimits,
  seedQualityFixture,
  seedSuperAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedQualityFixture();
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
  await page.goto(`${adminBaseUrl}/admin/quality/dashboard`);
  await expect(page.getByRole("heading", { name: "质量治理与发布门禁" })).toBeVisible({ timeout: 30_000 });

  for (const [section, label] of [
    ["dashboard", "概览"],
    ["requirements", "需求"],
    ["capabilities", "能力"],
    ["traceability", "追踪"],
    ["business-flows", "业务闭环"],
    ["gaps", "缺口"],
    ["risks", "风险"],
    ["waivers", "Waiver"],
    ["evidence", "证据"],
    ["gates", "门禁"],
    ["gate-runs", "门禁运行"],
    ["releases", "发布"],
    ["certifications", "认证"],
    ["audit", "审计"]
  ] as const) {
    await test.step(section, async () => {
      const navigation = page.getByRole("navigation", { name: "质量治理分区" });
      await navigation.getByRole("link", { name: label, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/admin/quality/${section}$`, "u"));
      await expect(page.getByRole("heading", { name: "质量治理与发布门禁" })).toBeVisible();
      await expect(page.locator("main")).not.toContainText(
        /artifact_reference_encrypted.*(?:s3|https)|password|private_key|secret_value/iu
      );
    });
  }
});

test("dashboard keeps production fail-closed policy visible", async ({ page }) => {
  await signIn(page);
  await page.goto(`${adminBaseUrl}/admin/quality/dashboard`);
  await expect(page.getByText("FAIL CLOSED")).toBeVisible();
  await expect(page.getByText(/生产环境不接受 Conditional Go/u)).toBeVisible();
});
