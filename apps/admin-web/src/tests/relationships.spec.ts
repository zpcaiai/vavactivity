import { describe, expect, it } from "vitest";

import { relationshipSectionPermissions, router } from "@/router";

const sections = ["dashboard", "journeys", "stages", "proposals", "pauses", "endings", "milestones", "checkins", "reminders", "audit"];

describe("relationship operations routes", () => {
  it("permission-gates every operations view", () => {
    expect(Object.keys(relationshipSectionPermissions).sort()).toEqual([...sections].sort());
    for (const section of sections) {
      const route = router.getRoutes().find((candidate) => candidate.name === `admin-relationships-${section}`);
      expect(route).toBeTruthy();
      expect(route?.meta.permission).toBe(relationshipSectionPermissions[section]);
    }
  });

  it("offers safety controls but no member decision route", () => {
    const paths = router.getRoutes().map((route) => route.path).filter((path) => path.includes("/admin/relationships"));
    expect(paths).toContain("/admin/relationships/journeys/:id");
    expect(paths.join("\n")).not.toMatch(/accept-stage|confirm-relationship|restore-ended|accept-resume/u);
  });
});
