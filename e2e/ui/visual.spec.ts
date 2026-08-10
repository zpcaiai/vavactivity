import { expect, test } from "@playwright/test";

const surfaces = [
  { name: "user-entry", url: "http://localhost:5173/" },
  { name: "admin-login", url: "http://localhost:5174/admin/login" }
];

for (const surface of surfaces) {
  test(`${surface.name} renders a reviewable visual artifact`, async ({ page }, testInfo) => {
    await page.goto(surface.url);
    await expect(page.locator("body")).not.toContainText("[plugin:vite:css]");
    await expect(page.locator("main")).toBeVisible();
    const screenshot = await page.screenshot({ fullPage: true });
    await testInfo.attach(`${surface.name}.png`, { body: screenshot, contentType: "image/png" });
  });
}
