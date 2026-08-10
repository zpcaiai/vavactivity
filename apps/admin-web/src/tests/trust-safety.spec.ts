import { describe, expect, it } from "vitest";

import { router, safetySectionPermissions } from "@/router";

const sections = [
  "reports",
  "cases",
  "moderation",
  "harassment",
  "fraud",
  "restrictions",
  "appeals",
  "rules",
  "red-team",
  "audit"
];

describe("Trust & Safety operations routes", () => {
  it("permission-gates every operations view", () => {
    expect(Object.keys(safetySectionPermissions).sort()).toEqual([...sections].sort());
    for (const section of sections) {
      const route = router
        .getRoutes()
        .find((candidate) => candidate.name === `admin-trust-safety-${section}`);
      expect(route).toBeTruthy();
      expect(route?.meta.permission).toBe(safetySectionPermissions[section]);
    }
  });

  it("does not expose reporter identity or automated permanent-ban routes", () => {
    const paths = router
      .getRoutes()
      .map((route) => route.path)
      .filter((path) => path.includes("trust-safety"));
    expect(paths.join("\n")).not.toMatch(/reporter-identity|auto-permanent-ban|raw-evidence/u);
  });
});
