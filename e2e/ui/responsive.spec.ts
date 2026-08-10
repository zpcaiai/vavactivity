import { expect, test } from "@playwright/test";

const surfaces = [
  { name: "user", url: "http://localhost:5173/" },
  { name: "admin", url: "http://localhost:5174/admin/login" }
];

for (const viewport of [
  { name: "mobile", width: 390, height: 844 },
  { name: "desktop", width: 1440, height: 900 }
]) {
  for (const surface of surfaces) {
    test(`${surface.name} entry fits the ${viewport.name} viewport`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto(surface.url);
      await expect(page.locator("body")).not.toContainText("[plugin:vite:css]");
      await expect(page.locator("main")).toBeVisible();
      const dimensions = await page.evaluate(() => ({
        viewport: document.documentElement.clientWidth,
        content: document.documentElement.scrollWidth
      }));
      expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport + 1);
    });
  }
}
