import { defineConfig, devices } from "@playwright/test";

const userWebUrl = process.env.E2E_USER_WEB_URL ?? "http://localhost:5173";
const adminWebUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";
const apiBaseUrl = process.env.E2E_API_BASE_URL ?? "http://localhost:8000/api/v1";
const apiProxyTarget = new URL(apiBaseUrl).origin;
const reuseExistingServer = process.env.CI !== "true";

function viteCommand(packageName: "@vav/user-web" | "@vav/admin-web", rawUrl: string) {
  const url = new URL(rawUrl);
  if (!new Set(["localhost", "127.0.0.1", "::1"]).has(url.hostname)) {
    throw new Error(`Playwright may only start a Vite server on loopback, received ${url.hostname}`);
  }
  const port = url.port || (url.protocol === "https:" ? "443" : "80");
  return `corepack pnpm --filter ${packageName} exec vite --host 127.0.0.1 --port ${port}`;
}

const webServer = [];
if (process.env.E2E_START_LOCAL_API === "1") {
  webServer.push({
    command: "bash scripts/e2e/start-local-api.sh",
    url: `${apiBaseUrl}/health/ready`,
    reuseExistingServer,
    timeout: 120_000
  });
}
if (process.env.E2E_EXTERNAL_WEBSERVERS !== "1") {
  webServer.push(
    {
      command: viteCommand("@vav/user-web", userWebUrl),
      url: userWebUrl,
      env: { VITE_API_BASE_URL: "/api/v1", VITE_API_PROXY_TARGET: apiProxyTarget },
      reuseExistingServer,
      timeout: 120_000
    },
    {
      command: viteCommand("@vav/admin-web", adminWebUrl),
      url: `${adminWebUrl}/admin/login`,
      env: { VITE_API_BASE_URL: "/api/v1", VITE_API_PROXY_TARGET: apiProxyTarget },
      reuseExistingServer,
      timeout: 120_000
    }
  );
}

export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["storybook/**"],
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  outputDir: "build/playwright-results",
  reporter: [
    ["line"],
    ["html", { outputFolder: "build/playwright-report", open: "never" }]
  ],
  use: {
    baseURL: userWebUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure"
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ],
  webServer
});
