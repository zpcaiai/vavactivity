import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  seedKnowledgeFixture,
  seedSuperAdmin
} from "./helpers";

test.beforeAll(() => {
  seedKnowledgeFixture();
  seedSuperAdmin();
});

test("an authorized operator inspects provenance and runs hybrid retrieval", async ({ page }) => {
  await page.goto("http://localhost:5174/admin/login");
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  await page.goto("http://localhost:5174/admin/knowledge");
  await expect(page.getByRole("heading", { name: "知识库中心", level: 2 })).toBeVisible();
  await page.getByRole("tab", { name: "文档与版本" }).click();
  await expect(page.getByText("healthy-boundaries-zh")).toBeVisible();
  await page.getByRole("tab", { name: "混合检索调试" }).click();
  await page.getByRole("button", { name: "运行授权检索" }).click();
  await expect(page.getByText("healthy-boundaries-zh · v1")).toBeVisible();
  await page.getByRole("tab", { name: "评测门禁" }).click();
  await expect(page.getByText("32 个案例")).toBeVisible();
  await page.getByRole("tab", { name: "私有导入向导" }).click();
  await page.getByLabel("知识文档文件").setInputFiles({
    name: "e2e-boundaries.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# E2E private import\n\nThis version requires authorization and review.")
  });
  await page.getByLabel("文档代码").fill(`e2e-private-${Date.now()}`);
  await page.getByLabel("文档标题").fill("E2E private provenance import");
  await page.getByRole("button", { name: "创建私有上传并校验" }).click();
  await expect(page.getByText("等待授权与人工复核")).toBeVisible();
});
