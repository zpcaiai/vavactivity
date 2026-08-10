import { describe, expect, it } from "vitest";
import { experienceSectionPermissions } from "@/router";

describe("experience control plane", () => {
  it("registers every governed operator view with an explicit permission", () => {
    expect(Object.keys(experienceSectionPermissions)).toEqual([
      "dashboard", "ia", "routes", "navigation", "tasks", "journeys", "handoffs", "search-governance", "help", "support", "dead-ends", "analytics", "evidence", "release", "audit"
    ]);
    expect(Object.values(experienceSectionPermissions).every((permission) => permission.startsWith("experience."))).toBe(true);
  });
});
