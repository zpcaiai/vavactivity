import { expect, test } from "@playwright/test";
import {
  resetLoginRateLimits,
  seedExperienceFixture,
  seedSuperAdmin,
  signInAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedExperienceFixture();
  seedSuperAdmin();
});

test("administrator can inspect every experience governance view", async ({ page }) => {
  await signInAdmin(page);
  await page.goto(`${adminBaseUrl}/admin/experience/dashboard`);
  await expect(page.getByRole("heading", { name: "信息架构与体验闭环" })).toBeVisible({
    timeout: 30_000
  });
  for (const [section, label] of [
    ["dashboard", "概览"],
    ["ia", "信息架构"],
    ["routes", "路由"],
    ["navigation", "导航"],
    ["tasks", "任务"],
    ["journeys", "旅程"],
    ["handoffs", "Handoff"],
    ["search-governance", "搜索治理"],
    ["help", "帮助"],
    ["support", "支持"],
    ["dead-ends", "死路检测"],
    ["analytics", "分析"],
    ["evidence", "证据"],
    ["release", "发布"],
    ["audit", "审计"]
  ] as const) {
    await test.step(section, async () => {
      const navigation = page.getByRole("navigation", { name: "体验治理分区" });
      await navigation.getByRole("link", { name: label, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/admin/experience/${section}$`, "u"));
      await expect(page.getByRole("heading", { name: "信息架构与体验闭环" })).toBeVisible();
    });
  }
});
