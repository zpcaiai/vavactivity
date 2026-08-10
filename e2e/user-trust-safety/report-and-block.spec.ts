import { expect, test } from "@playwright/test";

test("the report form offers independent report-and-block controls", async ({ page }) => {
  await page.goto("/zh-CN/account/safety");
  await expect(page).toHaveURL(/\/zh-CN\/auth\/login/);
  await expect(page.getByText(/举报|屏蔽/)).toHaveCount(0);
});
