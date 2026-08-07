import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ bootstrap: vi.fn(), accessToken: "token" }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => auth }));

import { relationshipsApi } from "@/features/relationships/api";
import { router } from "@/router";

describe("relationship journey client", () => {
  beforeEach(() => { vi.restoreAllMocks(); auth.bootstrap.mockResolvedValue(undefined); });

  it("exposes the full participant journey routes", () => {
    const paths = router.getRoutes().map((route) => route.path);
    expect(paths).toContain("/:locale(zh-CN|zh-TW|en)/account/relationships");
    expect(paths).toContain("/:locale(zh-CN|zh-TW|en)/account/relationships/:id/reflections");
  });

  it("uses an idempotency key for a stage proposal", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("11111111-1111-4111-8111-111111111111");
    const request = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ data: { status: "pending" } }), { status: 200, headers: { "Content-Type": "application/json" } }));
    await relationshipsApi.proposeStage("journey/unsafe", "initial_contact", "愿意吗？");
    const [url, init] = request.mock.calls[0]!;
    const headers = new Headers(init?.headers);
    expect(url).toContain("/account/relationships/journey%2Funsafe/stage-proposals");
    expect(headers.get("Idempotency-Key")).toBe("stage-proposal-11111111-1111-4111-8111-111111111111");
  });
});
