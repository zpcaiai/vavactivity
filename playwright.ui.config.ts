import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e/ui",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  outputDir: "build/ui/playwright-results",
  reporter: [["html", { outputFolder: "build/ui/playwright-report", open: "never" }]],
  use: {
    baseURL: process.env.E2E_USER_WEB_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "on"
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ]
});
