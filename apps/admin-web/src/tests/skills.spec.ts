import { describe, expect, it } from "vitest";

import { router, skillSectionPermissions } from "@/router";

describe("governed Skill console routes", () => {
  it("permission-gates every Skill console view", () => {
    for (const [section, permission] of Object.entries(skillSectionPermissions)) {
      const route = router.getRoutes().find((candidate) => candidate.name === `admin-skills-${section}`);
      expect(route).toBeTruthy();
      expect(route?.meta.permission).toBe(permission);
    }
  });

  it("does not expose direct privilege or sensitive execution routes", () => {
    const paths = router.getRoutes().map((route) => route.path).filter((path) => path.includes("skills"));
    expect(paths.join("\n")).not.toMatch(/grant-admin|raw-secret|force-publish|sensitive-output/u);
  });
});
