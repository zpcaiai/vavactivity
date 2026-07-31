import { describe, expect, it } from "vitest";

import { router } from "@/router";

describe("user authentication routes", () => {
  it("exposes every account recovery and session route", () => {
    const names = router.getRoutes().map((route) => route.name);

    expect(names).toEqual(
      expect.arrayContaining([
        "login",
        "register",
        "verify-email",
        "forgot-password",
        "reset-password",
        "account-security",
        "account-sessions"
      ])
    );
  });
});
