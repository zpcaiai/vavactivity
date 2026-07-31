import { expect, test } from "@playwright/test";

import { adminEmail, adminPassword, seedSuperAdmin } from "./helpers";

test.beforeAll(() => {
  seedSuperAdmin();
});

test("an operator publishes a free SKU and it becomes visible in the public catalog", async ({
  page
}) => {
  const suffix = Date.now();
  const code = `E2E_DIGITAL_${suffix}`;
  const publicName = `E2E 数字服务 ${suffix}`;

  await page.goto("http://localhost:5174/admin/login");
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  await page.goto("http://localhost:5174/admin/catalog/products");

  await page.getByRole("button", { name: "新建", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "新建商品管理" });
  await dialog.getByLabel("编码").fill(code);
  await dialog.getByLabel("内部名称").fill(publicName);
  await dialog.getByLabel("公开名称").fill(publicName);
  await dialog.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByText(code)).toBeVisible();

  await page.getByText(code).click();
  await expect(page).toHaveURL(/\/admin\/catalog\/products\/[0-9a-f-]+$/);

  await page.getByRole("button", { name: /zh-CN · draft/ }).click();
  const localizationDialog = page.getByRole("dialog", { name: "商品多语言内容" });
  await localizationDialog
    .locator("label")
    .filter({ hasText: "翻译状态" })
    .locator(".el-select")
    .click();
  await page.getByRole("option", { name: "已就绪" }).click();
  await localizationDialog.getByRole("button", { name: "保存翻译" }).click();
  await expect(page.getByRole("button", { name: /zh-CN · ready/ })).toBeVisible();

  await page.getByRole("button", { name: "新建 SKU" }).click();
  const skuDialog = page.getByRole("dialog", { name: "新建 SKU" });
  await skuDialog.getByLabel("SKU 编码").fill(`${code}_FREE`);
  await skuDialog.getByLabel("内部名称").fill(`${publicName} 免费 SKU`);
  await skuDialog.locator("label").filter({ hasText: "计费类型" }).locator(".el-select").click();
  await page.getByRole("option", { name: "免费" }).click();
  await skuDialog.getByLabel("数字服务编码").fill(`e2e-service-${suffix}`);
  await skuDialog.getByRole("button", { name: "保存", exact: true }).click();

  await page.getByRole("button", { name: "启用", exact: true }).click();
  await page.getByRole("button", { name: "提交审核" }).click();
  await page.getByRole("button", { name: "上架" }).click();
  await expect(page.getByText(`${code} · active`)).toBeVisible();

  await page.goto("http://localhost:5173/zh-CN/services");
  await expect(page.getByRole("heading", { name: publicName })).toBeVisible();
});
