import { expect, test } from "@playwright/test";

test("safety support is crisis-first and never requires confrontation", async ({ page }) => {
  await page.goto("/zh-CN/safety-support");
  await expect(page.getByRole("heading", { name: "安全支持" })).toBeVisible();
  await expect(page.getByText(/即时人身危险.*当地紧急服务/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "你不需要先与对方沟通" })).toBeVisible();
  await expect(page.getByText(/被举报者不会看到你的身份、描述、证据或案件优先级/)).toBeVisible();
});
test("protected safety routes require an authenticated member", async ({ page }) => {
  for (const path of ["reports", "blocks", "restrictions", "appeals"]) {
    await page.goto(`/zh-CN/account/safety/${path}`);
    await expect(page).toHaveURL(/\/zh-CN\/auth\/login/);
  }
});
