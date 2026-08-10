import { describe, expect, it } from "vitest";
import { dataGovernanceSectionPermissions } from "@/router";

describe("data governance console", () => {
  it("registers every governed integrity section", () => {
    expect(Object.keys(dataGovernanceSectionPermissions)).toHaveLength(16);
    expect(dataGovernanceSectionPermissions.erasures).toBe("data.erasures.read");
    expect(dataGovernanceSectionPermissions.backfills).toBe("data.backfills.read");
  });
});
