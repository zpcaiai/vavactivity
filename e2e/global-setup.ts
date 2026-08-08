import { execFileSync } from "node:child_process";

function dockerCompose(args: string[]): string {
  return execFileSync("docker", ["compose", ...args], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  }).trim();
}

async function waitForApiReady(apiBaseUrl: string): Promise<void> {
  const configuredTimeout = Number(process.env.E2E_API_READY_TIMEOUT_MS ?? "60000");
  const timeoutMs = Number.isFinite(configuredTimeout) && configuredTimeout > 0 ? configuredTimeout : 60_000;
  const deadline = Date.now() + timeoutMs;
  let lastResult = "no response";

  while (Date.now() < deadline) {
    const requestTimeout = Math.max(1, Math.min(5_000, deadline - Date.now()));
    try {
      const response = await fetch(`${apiBaseUrl}/health/ready`, {
        signal: AbortSignal.timeout(requestTimeout)
      });
      if (response.ok) return;
      lastResult = `HTTP ${response.status}`;
    } catch (cause) {
      lastResult = cause instanceof Error ? cause.message : String(cause);
    }

    const delay = Math.min(1_000, Math.max(0, deadline - Date.now()));
    if (delay > 0) await new Promise((resolve) => setTimeout(resolve, delay));
  }

  throw new Error(
    `E2E API is not ready at ${apiBaseUrl} after ${timeoutMs}ms (${lastResult}). ` +
      "Start it first or set E2E_START_LOCAL_API=1."
  );
}

export default async function globalSetup() {
  const apiBaseUrl = process.env.E2E_API_BASE_URL ?? "http://localhost:8000/api/v1";
  await waitForApiReady(apiBaseUrl);

  if (process.env.VAV_E2E_SEED_MODE !== "local" && process.env.VAV_E2E_SKIP_RATE_LIMIT_RESET !== "1") {
    const output = dockerCompose([
      "exec",
      "-T",
      "redis",
      "redis-cli",
      "--raw",
      "--scan",
      "--pattern",
      "rate:*"
    ]);
    const keys = output.split(/\r?\n/u).filter(Boolean);
    for (let offset = 0; offset < keys.length; offset += 100) {
      dockerCompose([
        "exec",
        "-T",
        "redis",
        "redis-cli",
        "UNLINK",
        ...keys.slice(offset, offset + 100)
      ]);
    }
  }
}
