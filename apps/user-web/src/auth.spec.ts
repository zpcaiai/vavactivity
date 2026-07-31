import { describe, expect, it } from "vitest";

import { router } from "@/router";
import { normalizeLoginIdentifier } from "@/stores/auth";

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

  it("maps the visible test login to its seeded email identity", () => {
    expect(normalizeLoginIdentifier("test")).toBe("test@example.com");
    expect(normalizeLoginIdentifier(" Test ")).toBe("test@example.com");
    expect(normalizeLoginIdentifier("member@example.com")).toBe("member@example.com");
  });
});
