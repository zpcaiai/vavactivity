import { describe, expect, it } from "vitest";
import { assertSafeRoute, localizeRoute } from "../src";

describe("navigation contracts", () => {
  it("localizes identifier-only paths", () => expect(localizeRoute("/{locale}/account", "zh-CN")).toBe("/zh-CN/account"));
  it("rejects sensitive query values", () => expect(() => assertSafeRoute({ route_code: "unsafe", route_path: "/x?email=a", authentication_required: false, permission_codes: [] })).toThrow(/sensitive/));
});
