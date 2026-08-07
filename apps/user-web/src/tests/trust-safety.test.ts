import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ bootstrap: vi.fn(), accessToken: "token" }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => auth }));

import { safetyApi } from "@/features/trust-safety/api";
import { router } from "@/router";

describe("member Trust & Safety client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    auth.bootstrap.mockResolvedValue(undefined);
  });

  it("exposes support, report, block, restriction and appeal routes", () => {
    const paths = router.getRoutes().map((route) => route.path);
    for (const suffix of [
      "safety-support",
      "account/safety",
      "account/safety/reports",
      "account/safety/blocks",
      "account/safety/restrictions",
      "account/safety/appeals"
    ]) {
      expect(paths).toContain(`/:locale(zh-CN|zh-TW|en)/${suffix}`);
    }
  });

  it("keeps report and block independent while supporting report-and-block", async () => {
    const request = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: { id: "report" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    await safetyApi.report({
      target_type: "user",
      reported_user_id: "11111111-1111-4111-8111-111111111111",
      category: "harassment",
      block_user: true,
      immediate_danger: false,
      idempotency_key: "report-idempotency-key"
    });
    expect(JSON.parse(String(request.mock.calls[0]?.[1]?.body))).toMatchObject({
      block_user: true,
      category: "harassment"
    });
  });
});
