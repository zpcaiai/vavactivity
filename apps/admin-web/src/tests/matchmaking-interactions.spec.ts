import { describe, expect, it } from "vitest";

import { interactionSectionPermissions, router } from "@/router";

const REQUIRED_SECTIONS = [
  "dashboard",
  "pairs",
  "matches",
  "invitations",
  "contact-exchanges",
  "invalidations",
  "dead-letters",
  "incidents",
  "audit"
] as const;

describe("matchmaking interaction operations routes", () => {
  it("gates every redacted operations section with a backend permission", () => {
    expect(Object.keys(interactionSectionPermissions).sort()).toEqual(
      [...REQUIRED_SECTIONS].sort()
    );
    for (const section of REQUIRED_SECTIONS) {
      const route = router.getRoutes().find(
        (candidate) => candidate.name === `admin-matchmaking-interactions-${section}`
      );
      expect(route, `missing interaction section ${section}`).toBeTruthy();
      expect(route?.meta.permission).toBe(interactionSectionPermissions[section]);
      expect(route?.meta.interactionSection).toBe(section);
    }
  });

  it("has diagnostic and revocation routes but no route that fabricates a choice", () => {
    const paths = router.getRoutes().map((route) => route.path);
    expect(paths).toContain("/admin/matchmaking-interactions/pairs/:id");
    expect(paths).toContain("/admin/matchmaking-interactions/contact-exchanges/:id");
    const interactionPaths = paths.filter((path) => path.includes("matchmaking-interactions"));
    expect(interactionPaths.join("\n")).not.toMatch(
      /create-like|accept-invitation|submit-consent/u
    );
  });
});
