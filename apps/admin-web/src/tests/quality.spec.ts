import { describe, expect, it } from "vitest";

import { qualitySectionPermissions, router } from "@/router";

describe("fail-closed quality governance routes", () => {
  it("permission-gates every quality view", () => {
    for (const [section, permission] of Object.entries(qualitySectionPermissions)) {
      const route = router.getRoutes().find((candidate) => candidate.name === `admin-quality-${section}`);
      expect(route).toBeTruthy();
      expect(route?.meta.permission).toBe(permission);
    }
  });

  it("exposes governed evidence and gate routes without bypass controls", () => {
    const paths = router.getRoutes().map((route) => route.path).filter((path) => path.includes("quality"));
    expect(paths).toContain("/admin/quality/evidence");
    expect(paths).toContain("/admin/quality/gates");
    expect(paths.join("\n")).not.toMatch(/force-go|skip-gate|self-approve|fake-evidence/u);
  });
});
