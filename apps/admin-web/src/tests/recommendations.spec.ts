import { describe, expect, it } from "vitest";

import {
  RECOMMENDATION_SENSITIVE_PERMISSION,
  RECOMMENDATION_SENSITIVE_SECTION,
  recommendationSections
} from "@/features/recommendations/sections";
import { recommendationSectionPermissions, router } from "@/router";

const REQUIRED_SECTIONS = [
  "dashboard",
  "strategies",
  "features",
  "constraints",
  "batches",
  "candidates",
  "diagnostics",
  "exposures",
  "cold-start",
  "feedback",
  "evaluations",
  "experiments",
  "incidents",
  "audit"
];

describe("recommendation operations centre routes", () => {
  it("maps every operations section to a backend permission", () => {
    for (const section of REQUIRED_SECTIONS) {
      expect(recommendationSectionPermissions[section]).toMatch(/^recommendations\./);
    }
    expect(Object.keys(recommendationSectionPermissions).sort()).toEqual(
      recommendationSections.map((item) => item[0]).sort()
    );
    for (const [section, , permission] of recommendationSections) {
      expect(recommendationSectionPermissions[section]).toBe(permission);
    }
  });

  it("gates the sensitive pair-diagnostics section on the separate sensitive permission", () => {
    expect(recommendationSectionPermissions[RECOMMENDATION_SENSITIVE_SECTION]).toBe(
      RECOMMENDATION_SENSITIVE_PERMISSION
    );
    expect(RECOMMENDATION_SENSITIVE_PERMISSION).toBe(
      "recommendations.candidates.sensitive.read"
    );
    expect(recommendationSectionPermissions["diagnostics"]).toBe(
      "recommendations.diagnostics.run"
    );
    expect(recommendationSectionPermissions[RECOMMENDATION_SENSITIVE_SECTION]).not.toBe(
      recommendationSectionPermissions["diagnostics"]
    );
  });

  it("registers one guarded route per section plus the detail routes", () => {
    const routes = router.getRoutes();
    for (const [section, , permission] of recommendationSections) {
      const registered = routes.find(
        (route) => route.name === `admin-recommendations-${section}`
      );
      expect(registered, `missing route for section ${section}`).toBeTruthy();
      expect(registered?.path).toBe(`/admin/recommendations/${section}`);
      expect(registered?.meta.permission).toBe(permission);
      expect(registered?.meta.recommendationSection).toBe(section);
    }
    expect(routes.map((route) => route.name)).toEqual(
      expect.arrayContaining([
        "admin-recommendations-strategy-detail",
        "admin-recommendations-batch-detail",
        "admin-recommendations-experiment-detail"
      ])
    );
    expect(
      routes.find((route) => route.name === "admin-recommendations-strategy-detail")?.path
    ).toBe("/admin/recommendations/strategies/:id");
  });
});
