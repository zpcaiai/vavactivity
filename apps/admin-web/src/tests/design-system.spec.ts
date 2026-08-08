import { describe, expect, it } from "vitest";

import { designSystemSectionPermissions, router } from "@/router";

describe("design system governance routes", () => {
  it("permission-gates all twelve governance views", () => {
    expect(Object.keys(designSystemSectionPermissions)).toHaveLength(12);
    for (const [section, permission] of Object.entries(designSystemSectionPermissions)) {
      const route = router.getRoutes().find((candidate) => candidate.name === `admin-design-system-${section}`);
      expect(route?.meta.permission).toBe(permission);
    }
  });

  it("contains independent review routes without bypass controls", () => {
    const paths = router.getRoutes().map((route) => route.path).filter((path) => path.includes("design-system"));
    expect(paths).toContain("/admin/design-system/accessibility");
    expect(paths).toContain("/admin/design-system/visual-regression");
    expect(paths.join("\n")).not.toMatch(/auto-approve|skip-review|force-release/u);
  });
});
