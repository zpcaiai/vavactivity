import { describe, expect, it } from "vitest";

import { adminModuleRoutes, router } from "./index";

describe("admin routes", () => {
  it("assigns a backend permission contract to every module route", () => {
    expect(adminModuleRoutes).toHaveLength(12);
    for (const route of adminModuleRoutes) {
      expect(route[3]).toMatch(/:view$/);
    }
  });

  it("redirects legacy module foundations to operational admin pages", () => {
    const expectedRedirects = new Map([
      ["/admin/content", "/admin/content/pages"],
      ["/admin/orders", "/admin/commerce/orders"],
      ["/admin/payments", "/admin/commerce/payments"],
      ["/admin/moderation", "/admin/trust-safety/moderation"],
      ["/admin/settings", "/admin/content/settings"],
      ["/admin/audit", "/admin/audit/auth"]
    ]);

    for (const [path, redirect] of expectedRedirects) {
      expect(router.resolve(path).redirectedFrom).toBeUndefined();
      const record = router.getRoutes().find((route) => route.path === path);
      expect(record?.redirect).toBe(redirect);
      expect(record?.components).toBeUndefined();
    }
  });
});
