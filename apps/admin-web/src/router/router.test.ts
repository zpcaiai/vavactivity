import { describe, expect, it } from "vitest";

import { adminModuleRoutes } from "./index";

describe("admin routes", () => {
  it("assigns a backend permission contract to every module route", () => {
    expect(adminModuleRoutes).toHaveLength(12);
    for (const route of adminModuleRoutes) {
      expect(route[3]).toMatch(/:view$/);
    }
  });
});

