import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/ui",
  testMatch: "storybook.spec.ts",
  reporter: [["list"], ["html", { outputFolder: "build/ui/storybook-playwright-report", open: "never" }]],
  use: { baseURL: "http://127.0.0.1:6006", ...devices["Desktop Chrome"], trace: "retain-on-failure" },
  webServer: {
    command: "corepack pnpm --filter @vav/design-system storybook",
    url: "http://127.0.0.1:6006/index.json",
    reuseExistingServer: false,
    timeout: 120_000
  }
});
