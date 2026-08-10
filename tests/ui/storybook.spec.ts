import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("every Storybook story renders and has no serious accessibility finding", async ({ page, request }) => {
  const response = await request.get("/index.json");
  expect(response.ok()).toBe(true);
  const catalog = await response.json() as { entries: Record<string, { id: string; type: string; title: string }> };
  const stories = Object.values(catalog.entries).filter((item) => item.type === "story");
  expect(stories.length).toBeGreaterThanOrEqual(3);
  for (const story of stories) {
    await page.goto(`/iframe.html?id=${encodeURIComponent(story.id)}&viewMode=story`);
    await expect(page.locator("#storybook-root")).not.toBeEmpty();
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    const blocking = results.violations.filter((item) => ["serious", "critical"].includes(item.impact ?? ""));
    expect(blocking, `${story.title}: ${JSON.stringify(blocking, null, 2)}`).toEqual([]);
  }
});
