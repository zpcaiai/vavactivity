import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e/storybook",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  workers: 1,
  outputDir: "build/ui/storybook-playwright-results",
  reporter: [
    ["html", { outputFolder: "build/ui/storybook-playwright-report", open: "never" }]
  ],
  webServer: {
    command:
      "python3 -m http.server 6006 --bind 127.0.0.1 --directory apps/design-system/storybook-static",
    url: "http://127.0.0.1:6006",
    reuseExistingServer: true,
    timeout: 30_000
  },
  use: {
    baseURL: "http://127.0.0.1:6006",
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
