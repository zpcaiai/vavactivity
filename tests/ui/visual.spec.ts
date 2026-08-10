import { expect, test } from "@playwright/test";

const cases = [
  { code: "mobile-light", width: 360, height: 800, theme: "light", density: "comfortable" },
  { code: "tablet-dark", width: 768, height: 1024, theme: "dark", density: "comfortable" },
  { code: "desktop-light", width: 1440, height: 1000, theme: "light", density: "compact" },
  { code: "wide-high-contrast", width: 1920, height: 1080, theme: "high-contrast", density: "compact" }
] as const;

for (const item of cases) {
  test(`${item.code} matches the committed technical baseline`, async ({ page }) => {
    await page.setViewportSize({ width: item.width, height: item.height });
    await page.goto("/");
    await page.locator("html").evaluate((element, values) => {
      const target = element as HTMLElement;
      target.dataset.vavTheme = values.theme;
      target.dataset.vavDensity = values.density;
    }, { theme: item.theme, density: item.density });
    await expect(page).toHaveScreenshot(`${item.code}.png`, { fullPage: true, animations: "disabled", maxDiffPixelRatio: 0.001 });
  });
}
