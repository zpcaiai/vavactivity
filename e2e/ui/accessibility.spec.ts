import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const surfaces = [
  { name: "user", url: "http://localhost:5173/" },
  { name: "admin", url: "http://localhost:5174/admin/login" }
];

for (const surface of surfaces) {
  test(`${surface.name} entry has no serious accessibility violations`, async ({ page }) => {
    await page.goto(surface.url);
    await expect(page.locator("body")).not.toContainText("[plugin:vite:css]");
    const result = await new AxeBuilder({ page }).analyze();
    expect(
      result.violations.filter((item) => item.impact === "critical" || item.impact === "serious")
    ).toEqual([]);
  });
}
