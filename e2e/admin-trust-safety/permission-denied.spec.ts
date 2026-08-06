import { expect, test } from "@playwright/test";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test("anonymous access cannot open sensitive evidence or audit views", async ({ page }) => {
  for (const section of ["cases", "audit"]) {
    await page.goto(`${adminBaseUrl}/admin/trust-safety/${section}`);
    await expect(page).toHaveURL(/\/admin\/login/);
  }
});
