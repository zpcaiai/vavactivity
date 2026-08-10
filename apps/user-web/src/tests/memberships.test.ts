import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ bootstrap: vi.fn(), accessToken: "token" }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => auth }));

import { membershipApi } from "@/features/memberships/api";
import { router } from "@/router";

describe("membership client", () => {
  beforeEach(() => { vi.restoreAllMocks(); auth.bootstrap.mockResolvedValue(undefined); });

  it("exposes plan, account, usage, management and history routes", () => {
    const paths = router.getRoutes().map((route) => route.path);
    for (const suffix of ["membership/plans", "membership/plans/:planCode", "account/membership", "account/membership/benefits", "account/membership/usage", "account/membership/manage", "account/membership/history"]) {
      expect(paths).toContain(`/:locale(zh-CN|zh-TW|en)/${suffix}`);
    }
  });

  it("requires an explicit confirmation request with a unique idempotency key", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("11111111-1111-4111-8111-111111111111");
    const request = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ data: { id: "change", version: 1 } }), { status: 200, headers: { "Content-Type": "application/json" } }));
    await membershipApi.requestChange("pro", "upgrade");
    const [, init] = request.mock.calls[0]!;
    expect(JSON.parse(String(init?.body))).toMatchObject({ to_plan_code: "pro", change_type: "upgrade", idempotency_key: "membership-change-11111111-1111-4111-8111-111111111111" });
  });
});
