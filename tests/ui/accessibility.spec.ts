import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("design catalog has no serious axe violations and supports keyboard entry", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(page.getByRole("main")).toHaveAttribute("id", "main-content");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "跳到主要内容" })).toBeFocused();
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const blocking = results.violations.filter((item) => ["serious", "critical"].includes(item.impact ?? ""));
  expect(blocking, JSON.stringify(blocking, null, 2)).toEqual([]);
});

test("modal traps focus, closes with escape and restores focus", async ({ page }) => {
  await page.goto("/");
  const opener = page.getByRole("button", { name: "打开确认" });
  await opener.focus();
  await opener.click();
  await expect(page.getByRole("dialog", { name: "确认设计变更" })).toBeVisible();
  await expect(page.getByRole("button", { name: "关闭对话框" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(opener).toBeFocused();
});
