import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ bootstrap: vi.fn(), accessToken: "token" }));

vi.mock("@/stores/auth", () => ({ useAuthStore: () => auth }));

import {
  interactionApiForTests,
  matchmakingInteractionsApi
} from "@/features/matchmaking-interactions/api";

describe("matchmaking interaction client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    auth.bootstrap.mockResolvedValue(undefined);
  });

  it("creates operation-scoped idempotency keys", () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue(
      "11111111-1111-4111-8111-111111111111"
    );
    expect(interactionApiForTests.idempotencyKey("like")).toBe(
      "like-11111111-1111-4111-8111-111111111111"
    );
  });

  it("sends every choice write with authentication and an idempotency key", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue(
      "22222222-2222-4222-8222-222222222222"
    );
    const request = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: { outcome: "one_sided" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    await matchmakingInteractionsApi.like("item/unsafe");
    const [url, init] = request.mock.calls[0]!;
    const headers = new Headers(init?.headers);
    expect(url).toContain("/recommendations/item%2Funsafe/like");
    expect(headers.get("Authorization")).toBe("Bearer token");
    expect(headers.get("Idempotency-Key")).toBe(
      "like-22222222-2222-4222-8222-222222222222"
    );
  });

  it("preserves backend error codes for unavailable-state handling", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          data: null,
          error: { code: "INTERACTION_NOT_AVAILABLE", message: "当前互动已不可用" }
        }),
        { status: 409, headers: { "Content-Type": "application/json" } }
      )
    );
    await expect(matchmakingInteractionsApi.matches()).rejects.toMatchObject({
      message: "当前互动已不可用",
      code: "INTERACTION_NOT_AVAILABLE"
    });
  });
});
