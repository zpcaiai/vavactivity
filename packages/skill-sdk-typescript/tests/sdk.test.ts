import { describe, expect, it } from "vitest";

import {
  assertContextActive,
  effectivePermissions,
  fakeSkillContext,
  sensitiveAnnotations,
  validateUiExtension
} from "../src";

describe("Skill SDK authority boundaries", () => {
  it("intersects every permission layer", () => {
    expect([...effectivePermissions(
      ["profiles.self.read", "commerce.orders.create"],
      ["profiles.self.read"],
      ["profiles.self.read"],
      ["profiles.self.read"]
    )]).toEqual(["profiles.self.read"]);
  });

  it("stops cancelled and expired executions", () => {
    const controller = new AbortController();
    controller.abort();
    expect(() => assertContextActive(fakeSkillContext({ signal: controller.signal }))).toThrow("SKILL_CANCELLED");
    expect(() => assertContextActive(fakeSkillContext({ deadline: new Date(0) }))).toThrow("SKILL_DEADLINE_EXCEEDED");
  });

  it("preserves sensitive annotations", () => {
    expect(sensitiveAnnotations({
      type: "string",
      "x-vav-sensitive": true,
      "x-vav-log-policy": "redacted"
    })).toEqual({ "x-vav-sensitive": true, "x-vav-log-policy": "redacted" });
  });

  it("only allows sandboxed registered UI extension points", () => {
    expect(() => validateUiExtension({
      extensionPoint: "admin.dashboard.widget",
      component: "ui/dist/widget.js",
      permissions: ["skills.analytics.read"],
      sandbox: "iframe",
      contentSecurityPolicy: { connectSrc: ["self"] }
    })).not.toThrow();
    expect(() => validateUiExtension({
      extensionPoint: "admin.dashboard.widget",
      component: "https://attacker.example/widget.js",
      permissions: [],
      sandbox: "iframe",
      contentSecurityPolicy: { connectSrc: ["*"] }
    })).toThrow("UI_EXTENSION_REMOTE_SCRIPT_FORBIDDEN");
  });
});
