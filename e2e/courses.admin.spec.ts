import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  resetLoginRateLimits,
  seedCourseFixture,
  seedSuperAdmin
} from "./helpers";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedCourseFixture();
  seedSuperAdmin();
});

test("an authorized operator can use the course center", async ({ page }) => {
  await page.goto("http://localhost:5174/admin/login");
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  await page.goto("http://localhost:5174/admin/courses");
  await expect(page.getByRole("heading", { name: "课程中心", level: 2 })).toBeVisible();
  await expect(page.getByText("course-e2e-foundations")).toBeVisible();
  await expect(page.getByText("发布会生成不可变课程版本")).toBeVisible();
  await page.getByRole("tab", { name: "结构与课时" }).click();
  await expect(page.getByRole("button", { name: "新增章节" })).toBeVisible();
  await expect(page.getByRole("button", { name: "关联私有视频" })).toBeVisible();
  await page.getByRole("tab", { name: "报名与进度" }).click();
  await expect(page.getByRole("button", { name: "授权课程" })).toBeVisible();
  await page.getByRole("tab", { name: "证书" }).click();
  await expect(
    page.getByText("证书仅证明 VAV 课程完成，不宣称政府、学术或专业认证资质。")
  ).toBeVisible();
});
