import { describe, expect, it, vi } from "vitest";

import { createHostMessageHandler, iframePolicy, validateRegistration } from "../src";

const registration = {
  id: "vav.example.widget",
  extensionPoint: "admin.dashboard.widget" as const,
  assetPath: "ui/dist/widget.js",
  assetSha256: "a".repeat(64),
  permissions: ["skills.analytics.read"],
  connectSrc: ["self", "https://api.example.com"]
};

describe("Skill UI SDK", () => {
  it("builds a strict sandbox and CSP for a content-addressed same-origin asset", () => {
    const policy = iframePolicy(registration, "https://skills.example.com/artifacts/");
    expect(policy.sandbox).toBe("allow-scripts");
    expect(policy.src).toContain("sha256=" + "a".repeat(64));
    expect(policy.csp).toContain("default-src 'none'");
    expect(policy.csp).not.toContain("connect-src *");
  });

  it("rejects traversal, wildcard egress, duplicate permissions, and weak digests", () => {
    expect(() => validateRegistration({...registration, assetPath: "ui/dist/../evil.js"})).toThrow();
    expect(() => validateRegistration({...registration, connectSrc: ["*"]})).toThrow();
    expect(() => validateRegistration({...registration, permissions: ["skills.analytics.read", "skills.analytics.read"]})).toThrow();
    expect(() => validateRegistration({...registration, assetSha256: "abc"})).toThrow();
  });

  it("ignores spoofed messages and only invokes explicitly allowed host actions", async () => {
    const postMessage = vi.fn();
    const frameWindow = { postMessage } as unknown as Window;
    const invoke = vi.fn(async () => ({ ok: true }));
    const handler = createHostMessageHandler({
      expectedOrigin: "https://skills.example.com",
      frameWindow,
      allowedActions: new Set(["skills.analytics.summary"]),
      invoke
    });
    const message = (origin: string, source: MessageEventSource | null, action: string) => ({
      origin,
      source,
      data: {
        protocol: "vav.skill-ui/v1",
        requestId: "request-123",
        type: "extension.invoke",
        payload: { action, input: {} }
      }
    } as MessageEvent<unknown>);
    await handler(message("https://attacker.example", frameWindow, "skills.analytics.summary"));
    await handler(message("https://skills.example.com", {} as Window, "skills.analytics.summary"));
    expect(invoke).not.toHaveBeenCalled();
    await handler(message("https://skills.example.com", frameWindow, "skills.admin.grant"));
    expect(invoke).not.toHaveBeenCalled();
    expect(postMessage).toHaveBeenLastCalledWith(expect.objectContaining({type: "host.error"}), "https://skills.example.com");
    await handler(message("https://skills.example.com", frameWindow, "skills.analytics.summary"));
    expect(invoke).toHaveBeenCalledOnce();
    expect(postMessage).toHaveBeenLastCalledWith(expect.objectContaining({type: "host.response"}), "https://skills.example.com");
  });
});
