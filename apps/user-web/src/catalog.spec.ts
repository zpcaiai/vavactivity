import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ProductPrice from "@/features/catalog/components/ProductPrice.vue";
import { router } from "@/router";

describe("public catalog", () => {
  it("exposes catalog, category, product, plan and membership routes", () => {
    const names = router.getRoutes().map((route) => route.name);
    expect(names).toEqual(
      expect.arrayContaining([
        "services",
        "service-category",
        "product-detail",
        "activities",
        "courses",
        "counseling",
        "ai-plans",
        "membership"
      ])
    );
  });

  it("formats TWD with its zero-decimal exponent", () => {
    const wrapper = mount(ProductPrice, {
      props: { amountMinor: 1200, currency: "TWD", exponent: 0 }
    });
    expect(wrapper.text()).toContain("1,200");
    expect(wrapper.text()).not.toContain("120,000");
  });
});
