import { describe, expect, it } from "vitest";

import { router } from "@/router";

describe("administration CMS routes", () => {
  it("registers pages, articles, testimonials, media and contact queues", () => {
    const names = router.getRoutes().map((route) => route.name);
    expect(names).toEqual(
      expect.arrayContaining([
        "admin-content-pages",
        "admin-content-articles",
        "admin-content-testimonials",
        "admin-content-media",
        "admin-content-navigation",
        "admin-content-settings",
        "admin-contact-submissions"
      ])
    );
  });
});
