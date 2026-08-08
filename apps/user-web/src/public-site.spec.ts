import { describe, expect, it } from "vitest";

import { router } from "@/router";

describe("public CMS routes", () => {
  it("registers fixed pages, article and testimonial details, and contact", () => {
    const names = router.getRoutes().map((route) => route.name);
    expect(names).toEqual(
      expect.arrayContaining([
        "home",
        "about",
        "articles",
        "article-detail",
        "stories",
        "story-detail",
        "contact",
        "privacy",
        "terms",
        "refund-policy",
        "ai-disclaimer"
      ])
    );
  });
});
