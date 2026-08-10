import { expect, test } from "@playwright/test";
import { requiredViewports } from "@vav/ui-testing";

for (const viewport of requiredViewports) {
  test(`${viewport.code} has no horizontal overflow and keeps touch targets`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    const sizes = await page.locator("button, select").evaluateAll((items) => items.map((item) => {
      const box = item.getBoundingClientRect();
      return { label: item.textContent?.trim() || item.getAttribute("aria-label"), width: box.width, height: box.height };
    }));
    expect(sizes.filter((item) => item.width < 44 || item.height < 44), JSON.stringify(sizes, null, 2)).toEqual([]);
    await expect(page.locator("#patterns")).toBeVisible();
  });
}
