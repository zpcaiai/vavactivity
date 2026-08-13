import { beforeEach, describe, expect, it, vi } from "vitest";

const bootstrap = vi.fn(async () => undefined);
vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ bootstrap, accessToken: "member-token", user: { id: "member" } })
}));

import { discoveryApiClient } from "@/features/discovery/api";
import { useDiscoveryFeed } from "@/features/discovery/composables/useDiscoveryFeed";
import type { DiscoveryFeed } from "@/features/discovery/types";

function feed(overrides: Partial<DiscoveryFeed> = {}): DiscoveryFeed {
  return {
    scope: "local",
    city_code: "SH",
    city_source: "manual",
    city_is_confirmed: true,
    suggested_city_code: null,
    fallback_applied: false,
    fallback_reason: "not_applied",
    local_count: 3,
    items: [],
    ...overrides
  };
}

function stubFetch(payload: DiscoveryFeed, preference: unknown = { city_code: "SH", allow_ip_suggestion: true, confirmed_at: "2026-08-01T00:00:00Z" }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () =>
        url.includes("/city-preference") ? { data: preference } : { data: payload }
    }))
  );
}

describe("discovery feed", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("flags an IP-derived city the member has not confirmed", async () => {
    stubFetch(feed({ city_source: "ip_suggestion", city_is_confirmed: false }));
    const discovery = useDiscoveryFeed();
    await discovery.load();

    expect(discovery.showsUnconfirmedCity.value).toBe(true);
  });

  it("does not flag a city the member chose themselves", async () => {
    stubFetch(feed());
    const discovery = useDiscoveryFeed();
    await discovery.load();

    expect(discovery.showsUnconfirmedCity.value).toBe(false);
  });

  it("offers a switch only when the suggestion differs from the current city", async () => {
    stubFetch(feed({ suggested_city_code: "SH" }));
    const same = useDiscoveryFeed();
    await same.load();
    expect(same.suggestedSwitch.value).toBeNull();

    stubFetch(feed({ suggested_city_code: "BJ" }));
    const different = useDiscoveryFeed();
    await different.load();
    expect(different.suggestedSwitch.value).toBe("BJ");
  });

  it("reports when the city filter stopped filtering", async () => {
    stubFetch(
      feed({ scope: "national", fallback_applied: true, fallback_reason: "local_results_empty" })
    );
    const discovery = useDiscoveryFeed();
    await discovery.load();

    // GEO-001: a filter that silently stops filtering is indistinguishable
    // from a broken one, so the UI has to be able to say it happened.
    expect(discovery.fellBackToNational.value).toBe(true);
    expect(discovery.feed.value?.fallback_reason).toBe("local_results_empty");
  });

  it("keeps the feed usable when the saved preference cannot be read", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.includes("/city-preference")) {
          return { ok: false, status: 500, json: async () => ({ error: { message: "down" } }) };
        }
        return { ok: true, status: 200, json: async () => ({ data: feed() }) };
      })
    );

    const discovery = useDiscoveryFeed();
    await discovery.load();

    expect(discovery.error.value).toBeNull();
    expect(discovery.feed.value?.city_code).toBe("SH");
    expect(discovery.preference.value).toBeNull();
  });

  it("sends a one-off city override as a query parameter, not a saved preference", async () => {
    stubFetch(feed());
    await discoveryApiClient.feed({ cityCode: "BJ" });

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/account/discovery/feed?city_code=BJ"),
      expect.objectContaining({ credentials: "include" })
    );
    expect(fetch).not.toHaveBeenCalledWith(
      expect.stringContaining("/account/city-preference"),
      expect.objectContaining({ method: "PUT" })
    );
  });

  it("clears the preference with an explicit null rather than omitting it", async () => {
    stubFetch(feed());
    await discoveryApiClient.setCityPreference({ city_code: null, allow_ip_suggestion: true });

    const call = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls.find(
      ([, init]) => init?.method === "PUT"
    );
    expect(call).toBeDefined();
    expect(JSON.parse(String(call?.[1].body))).toEqual({
      city_code: null,
      allow_ip_suggestion: true
    });
  });
});
