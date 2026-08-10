import { test } from "@playwright/test";
import { resetLoginRateLimits } from "../../e2e/helpers";

// The complete matrix deliberately reuses one browser/IP for dozens of real
// authentication journeys. Reset only ephemeral abuse counters between tests;
// production limits and all durable application state remain unchanged.
export function installRateLimitReset() {
  test.beforeEach(() => {
    resetLoginRateLimits();
  });
}
