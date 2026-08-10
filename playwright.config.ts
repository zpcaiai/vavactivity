import { defineConfig, devices } from "@playwright/test";

const captureAll = process.env.E2E_CAPTURE_ALL === "1";
const captureVideo = process.env.E2E_CAPTURE_VIDEO === "1";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "line",
  timeout: 45_000,
  expect: {
    timeout: 10_000
  },
  use: {
    baseURL: process.env.E2E_USER_WEB_URL ?? "http://localhost:5173",
    trace: captureAll ? "on" : "retain-on-failure",
    screenshot: captureAll ? "on" : "only-on-failure",
    video: captureVideo ? "on" : "off"
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        channel: process.env.PLAYWRIGHT_CHANNEL ?? "chrome"
      }
    }
  ],
  outputDir: "test-results/playwright"
});
