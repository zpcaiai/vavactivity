import { describe, expect, it } from "vitest";

import { router, systemSectionPermissions } from "@/router";

describe("production system operations routes", () => {
  it("permission-gates every system operations view", () => {
    for (const [section, permission] of Object.entries(systemSectionPermissions)) {
      const route = router.getRoutes().find((candidate) => candidate.name === `admin-system-${section}`);
      expect(route).toBeTruthy();
      expect(route?.meta.permission).toBe(permission);
    }
  });

  it("does not expose secrets or unapproved direct-deploy routes", () => {
    const paths = router.getRoutes().map((route) => route.path).filter((path) => path.includes("system"));
    expect(paths.join("\n")).not.toMatch(/secret-value|credential|direct-deploy|force-activate/u);
  });
});
