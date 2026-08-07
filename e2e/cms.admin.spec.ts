import { expect, test } from "@playwright/test";

import { adminEmail, adminPassword, seedSuperAdmin } from "./helpers";

test.beforeAll(() => {
  seedSuperAdmin();
});

test("an editor creates structured content, marks translation ready and publishes it", async ({
  page,
  request
}) => {
  const suffix = Date.now();
  const slug = `e2e-content-${suffix}`;
  const title = `E2E 内容 ${suffix}`;

  await page.goto("http://localhost:5174/admin/login");
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  await page.goto("http://localhost:5174/admin/content/pages");

  await page.getByRole("button", { name: "创建草稿" }).click();
  const createDialog = page.getByRole("dialog", { name: "创建内容草稿" });
  await createDialog.getByLabel("内部名称").fill(title);
  await createDialog.getByLabel("Slug").fill(slug);
  await createDialog.getByLabel("标题").fill(title);
  await createDialog.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByText(slug)).toBeVisible();

  await page.getByText(slug).click();
  await expect(page).toHaveURL(/\/admin\/content\/pages\/[0-9a-f-]+$/);
  await page.locator("label").filter({ hasText: "翻译状态" }).locator(".el-select").click();
  await page.getByRole("option", { name: "已就绪" }).click();
  await page.getByRole("button", { name: "添加区块" }).click();
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByText("草稿已保存")).toBeVisible();

  await page.getByRole("button", { name: "提交审核" }).click();
  await page.getByRole("button", { name: "发布", exact: true }).click();
  await expect(page.getByText(new RegExp(`${slug} · published`))).toBeVisible();

  const response = await request.get(
    `http://localhost:8000/api/v1/public/content/pages/${slug}?locale=zh-CN`
  );
  expect(response.ok()).toBeTruthy();
  const payload = await response.json() as { data: { title: string } };
  expect(payload.data.title).toBe(title);
});
