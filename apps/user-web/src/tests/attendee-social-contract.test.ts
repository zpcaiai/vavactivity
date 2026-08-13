import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

describe("SOC-001 follow presentation", () => {
  it("uses server-computed mutuality instead of a truncated local set", () => {
    const page = readFileSync(
      resolve(srcDirectory, "features/attendee-social/pages/FollowsPage.vue"),
      "utf8"
    );
    const types = readFileSync(
      resolve(srcDirectory, "features/attendee-social/types.ts"),
      "utf8"
    );

    expect(types).toContain("is_mutual: boolean");
    expect(types).toContain('relation_kind: "follow"');
    expect(page).toContain('v-if="edge.is_mutual"');
    expect(page).not.toContain("followingIds");
  });

  it("shows a retryable notification-preference loading failure", () => {
    const page = readFileSync(
      resolve(srcDirectory, "features/attendee-social/pages/FollowsPage.vue"),
      "utf8"
    );

    expect(page).toContain("preferenceError.value = (caught as Error).message");
    expect(page).toContain('v-else-if="preferenceError"');
    expect(page).toContain('@click="loadPreferences"');
  });
});
