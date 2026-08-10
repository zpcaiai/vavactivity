import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

const userBaseUrl = process.env.E2E_USER_WEB_URL ?? "http://127.0.0.1:5173";
const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://127.0.0.1:5174";

type RuntimeFailures = {
  consoleErrors: string[];
  pageErrors: string[];
  serverErrors: string[];
};

function observeRuntime(page: Page): RuntimeFailures {
  const failures: RuntimeFailures = { consoleErrors: [], pageErrors: [], serverErrors: [] };
  page.on("console", (message) => {
    if (message.type() === "error") failures.consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => failures.pageErrors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 500) {
      failures.serverErrors.push(`${response.status()} ${response.url()}`);
    }
  });
  return failures;
}

async function assertReviewablePage(page: Page, testInfo: TestInfo, name: string) {
  await expect(page.locator("body")).not.toContainText("[plugin:vite:");
  await expect(page.locator("body")).not.toContainText("Internal Server Error");
  await expect(page.locator("main")).toBeVisible();
  await expect(page.locator("main")).not.toBeEmpty();
  await expect(page.locator("vite-error-overlay")).toHaveCount(0);

  const dimensions = await page.evaluate(() => ({
    viewportWidth: document.documentElement.clientWidth,
    contentWidth: document.documentElement.scrollWidth,
    bodyTextLength: document.body.innerText.trim().length
  }));
  expect(dimensions.bodyTextLength).toBeGreaterThan(20);
  expect(dimensions.contentWidth).toBeLessThanOrEqual(dimensions.viewportWidth + 1);

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations.filter(
      (violation) => violation.impact === "critical" || violation.impact === "serious"
    )
  ).toEqual([]);

  await testInfo.attach(`${name}.png`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png"
  });
}

function assertNoRuntimeFailures(failures: RuntimeFailures) {
  expect(failures.pageErrors, "uncaught browser errors").toEqual([]);
  expect(failures.serverErrors, "HTTP 5xx responses").toEqual([]);
  expect(failures.consoleErrors, "browser console errors").toEqual([]);
}

test("public language entry is operable and keyboard reachable", async ({ page }, testInfo) => {
  const failures = observeRuntime(page);
  await page.goto(`${userBaseUrl}/`);
  await assertReviewablePage(page, testInfo, "user-language-entry");

  const skipLink = page.locator("a.skip-link");
  await expect(skipLink).toHaveAttribute("href", "#main-content");
  await page.keyboard.press("Tab");
  await expect(skipLink).toBeFocused();
  await skipLink.press("Enter");
  await expect(page.locator("#main-content")).toBeVisible();

  assertNoRuntimeFailures(failures);
});

test("public catalog renders localized service content", async ({ page }, testInfo) => {
  const failures = observeRuntime(page);
  await page.goto(`${userBaseUrl}/zh-CN/services`);
  await assertReviewablePage(page, testInfo, "user-service-catalog");
  await expect(page.getByRole("heading").first()).toBeVisible();
  await expect(page.getByRole("link").first()).toBeVisible();
  assertNoRuntimeFailures(failures);
});

test("admin sign-in exposes the expected protected entry controls", async ({ page }, testInfo) => {
  const failures = observeRuntime(page);
  await page.goto(`${adminBaseUrl}/admin/login`);
  await assertReviewablePage(page, testInfo, "admin-login");
  await expect(page.getByLabel("管理员邮箱")).toBeEditable();
  await expect(page.getByLabel("密码")).toBeEditable();
  await expect(page.getByRole("button", { name: "安全登录" })).toBeEnabled();
  assertNoRuntimeFailures(failures);
});
