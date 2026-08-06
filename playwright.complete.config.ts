import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/complete-e2e",
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "line",
  timeout: 60_000,
  expect: { timeout: 12_000 },
  use: {
    baseURL: process.env.E2E_USER_WEB_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off"
  },
  projects: [{
    name: "complete-chromium",
    use: {
      ...devices["Desktop Chrome"],
      channel: process.env.PLAYWRIGHT_CHANNEL ?? "chrome"
    }
  }],
  outputDir: "test-results/complete-e2e"
});
