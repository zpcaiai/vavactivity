import { describe, expect, it } from "vitest";
import { processSectionPermissions } from "@/router";

describe("process governance console", () => {
  it("exposes every governed operating section with explicit permission", () => {
    expect(Object.keys(processSectionPermissions)).toHaveLength(13);
    expect(processSectionPermissions.compensations).toBe("process.compensations.read");
    expect(processSectionPermissions.certifications).toBe("process.certifications.read");
  });
});
