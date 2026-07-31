import { describe, expect, it } from "vitest";

import { router } from "@/router";

describe("administration catalog routes", () => {
  it("registers the complete product-center surface with RBAC metadata", () => {
    const routes = router.getRoutes();
    const names = routes.map((route) => route.name);
    expect(names).toEqual(
      expect.arrayContaining([
        "admin-catalog-products",
        "admin-catalog-product-edit",
        "admin-catalog-price-books",
        "admin-catalog-prices",
        "admin-catalog-inventory",
        "admin-catalog-promotions",
        "admin-catalog-coupons",
        "admin-catalog-pricing-simulate"
      ])
    );
    expect(
      routes.find((route) => route.name === "admin-catalog-inventory")?.meta
        .permission
    ).toBe("catalog.inventory.read");
  });
});
