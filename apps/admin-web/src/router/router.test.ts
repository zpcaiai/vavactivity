import { describe, expect, it } from "vitest";

import { adminModuleRoutes, router } from "./index";

describe("admin routes", () => {
  it("assigns a backend permission contract to every module route", () => {
    expect(adminModuleRoutes).toHaveLength(12);
    for (const route of adminModuleRoutes) {
      expect(route[3]).toMatch(/:view$/);
    }
  });

  it("redirects legacy administration URLs to working control planes", () => {
    const redirects = {
      "/admin/content": "/admin/content/pages",
      "/admin/orders": "/admin/commerce/orders",
      "/admin/payments": "/admin/commerce/payments",
      "/admin/moderation": "/admin/trust-safety/reports",
      "/admin/settings": "/admin/system/feature-flags",
      "/admin/audit": "/admin/audit/auth"
    };

    for (const [source, target] of Object.entries(redirects)) {
      expect(router.resolve(source).redirectedFrom).toBeUndefined();
      const record = router.getRoutes().find((route) => route.path === source);
      expect(record?.redirect).toBe(target);
    }
  });
});
