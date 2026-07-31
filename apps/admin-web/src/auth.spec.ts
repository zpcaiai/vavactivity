import { describe, expect, it } from "vitest";

import { router } from "@/router";

describe("administrator authentication routes", () => {
  it("keeps login and invitation acceptance public", () => {
    const login = router.getRoutes().find((route) => route.name === "admin-login");
    const invitation = router
      .getRoutes()
      .find((route) => route.name === "admin-accept-invitation");

    expect(login?.meta.public).toBe(true);
    expect(invitation?.meta.public).toBe(true);
  });
});
