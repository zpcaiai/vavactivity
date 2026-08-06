import { expect, test } from "@playwright/test";

test("administration platform preserves the governed route", async ({ page }) => {
  await page.goto("/admin/platform/dashboard");
  await expect(page).toHaveURL(/admin\/platform\/dashboard|login/);
});
