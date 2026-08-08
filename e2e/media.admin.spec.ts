import { Buffer } from "node:buffer";

import { expect, test } from "@playwright/test";

import { adminEmail, adminPassword, resetLoginRateLimits, seedSuperAdmin } from "./helpers";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedSuperAdmin();
});

test("an editor uploads a verified image with localized alternative text", async ({
  page
}) => {
  const filename = `e2e-media-${Date.now()}.png`;
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFElEQVR4nGNU9ohlwAaYsIoOWgkAoX4A2I+BA8YAAAAASUVORK5CYII=",
    "base64"
  );

  await page.goto("http://localhost:5174/admin/login");
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);

  await page.goto("http://localhost:5174/admin/content/media");
  await page.getByLabel("选择图片或 PDF").setInputFiles({
    name: filename,
    mimeType: "image/png",
    buffer: png
  });
  await page.getByLabel("替代文本").fill("用于媒体安全验收的蓝色方块");
  await page.getByRole("button", { name: "上传并验证" }).click();

  await expect(page.getByText("媒体内容、真实 MIME、SHA-256 与衍生尺寸已验证。")).toBeVisible();
  const card = page.locator(".media-card").filter({ hasText: filename });
  await expect(card).toContainText("public · ready");
  await expect(card.locator("img")).toBeVisible();
});
