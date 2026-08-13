import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({ grant: vi.fn() }));
vi.mock("@/features/profile-media/api", () => ({
  profileMediaApiClient: { grant: apiMocks.grant }
}));

import { useMediaGrants } from "@/features/profile-media/composables/useMediaGrants";
import type { MediaAsset, MediaGrant } from "@/features/profile-media/types";

const START = new Date("2026-08-13T00:00:00Z");

function asset(assetId = "asset-1"): MediaAsset {
  return {
    asset_id: assetId,
    kind: "photo",
    state: "active",
    moderation_state: "approved",
    rejection_reason_code: null,
    position: 1,
    duration_seconds: null,
    media_path: `/media/private/${assetId}`,
    is_publishable: true
  };
}

function grant(url: string, expiresAt: string): MediaGrant {
  return {
    media_path: "/media/private/token",
    media_url: url,
    expires_at: expiresAt,
    signature: "application-grant-signature",
    viewer_id: "viewer-1"
  };
}

describe("profile media grants", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(START);
    apiMocks.grant.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps the expiry and refreshes the URL before it expires", async () => {
    apiMocks.grant
      .mockResolvedValueOnce(grant("https://storage.example/first", "2026-08-13T00:02:00Z"))
      .mockResolvedValueOnce(grant("https://storage.example/fresh", "2026-08-13T00:06:00Z"));
    const media = useMediaGrants();

    await media.loadMediaGrants([asset()]);

    expect(media.grants.value["asset-1"]?.expires_at).toBe("2026-08-13T00:02:00Z");
    expect(media.mediaUrls.value["asset-1"]).toBe("https://storage.example/first");

    // Two-minute grant, refreshed with a 30-second safety margin.
    await vi.advanceTimersByTimeAsync(90_000);

    expect(apiMocks.grant).toHaveBeenCalledTimes(2);
    expect(media.mediaUrls.value["asset-1"]).toBe("https://storage.example/fresh");
    media.dispose();
  });

  it("handles a scheduled refresh failure and keeps the still-valid URL", async () => {
    apiMocks.grant
      .mockResolvedValueOnce(grant("https://storage.example/still-valid", "2026-08-13T00:02:00Z"))
      .mockRejectedValueOnce(new Error("grant service unavailable"))
      .mockResolvedValueOnce(grant("https://storage.example/recovered", "2026-08-13T00:06:00Z"));
    const media = useMediaGrants();
    await media.loadMediaGrants([asset()]);

    // The proactive refresh runs with 30 seconds left. Its rejection is handled
    // inside the timer rather than becoming an unhandled promise rejection.
    await vi.advanceTimersByTimeAsync(90_000);
    await Promise.resolve();

    expect(apiMocks.grant).toHaveBeenCalledTimes(2);
    expect(media.mediaUrls.value["asset-1"]).toBe("https://storage.example/still-valid");

    // If the retained URL later fails, the explicit media-error path clears it
    // and obtains a new grant.
    await media.refreshAfterMediaError("asset-1");
    expect(apiMocks.grant).toHaveBeenCalledTimes(3);
    expect(media.mediaUrls.value["asset-1"]).toBe("https://storage.example/recovered");
    media.dispose();
  });

  it("requests a fresh grant after a media load error without retry-looping", async () => {
    apiMocks.grant
      .mockResolvedValueOnce(grant("https://storage.example/expired", "2026-08-13T00:05:00Z"))
      .mockResolvedValueOnce(grant("https://storage.example/retry", "2026-08-13T00:05:00Z"));
    const media = useMediaGrants();
    await media.loadMediaGrants([asset()]);

    await media.refreshAfterMediaError("asset-1");

    expect(apiMocks.grant).toHaveBeenCalledTimes(2);
    expect(media.mediaUrls.value["asset-1"]).toBe("https://storage.example/retry");

    // A corrupt object can emit another error immediately. Hide it rather than
    // issuing grants forever; a later page reload remains an explicit retry.
    await media.refreshAfterMediaError("asset-1");
    expect(apiMocks.grant).toHaveBeenCalledTimes(2);
    expect(media.mediaUrls.value["asset-1"]).toBeUndefined();
    media.dispose();
  });
});
