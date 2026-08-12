import { describe, expect, it } from "vitest";

import { membershipSectionPermissions, router } from "@/router";

// `incidents` was removed: the backend's ADMIN_RESOURCE_PERMISSIONS has no such
// key, so the section answered 404 on every open and the page hid it by falling
// back to dashboard data.
const sections = ["dashboard", "plans", "plan-versions", "benefits", "sku-mappings", "accounts", "cycles", "changes", "quotas", "usage", "adjustments", "manual-grants", "trials", "reconciliation", "audit"];

describe("membership operations routes", () => {
  it("permission-gates every Batch 17 operations view", () => {
    expect(Object.keys(membershipSectionPermissions).sort()).toEqual([...sections].sort());
    for (const section of sections) {
      const route = router.getRoutes().find((candidate) => candidate.name === `admin-memberships-${section}`);
      expect(route).toBeTruthy();
      expect(route?.meta.permission).toBe(membershipSectionPermissions[section]);
    }
  });

  it("does not expose payment or direct quota mutation controls", () => {
    const paths = router.getRoutes().map((route) => route.path).filter((path) => path.includes("/admin/memberships"));
    expect(paths.join("\n")).not.toMatch(/mark-paid|set-subscription-active|overwrite-consumed|safety-bypass/u);
  });
});
