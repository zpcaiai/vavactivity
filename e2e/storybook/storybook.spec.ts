import { expect, test } from "@playwright/test";

test("the governed component catalog loads without a runtime error", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("body")).not.toContainText("Failed to fetch dynamically imported module");
  await expect(page.locator("body")).not.toContainText("[plugin:vite:css]");
  await expect(page.locator("#storybook-explorer-menu")).toBeVisible();
});
