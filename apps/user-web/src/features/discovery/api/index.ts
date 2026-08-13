import { resolveApiBaseUrl } from "@/config/api";
import type {
  CityPreference,
  DiscoveryFeed,
  ShareCard,
  VenueLocation
} from "@/features/discovery/types";
import { useAuthStore } from "@/stores/auth";

const baseUrl = resolveApiBaseUrl();

export async function discoveryApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, credentials: "include" });
  const payload = (await response.json()) as {
    data: T;
    error?: { message: string; code?: string; details?: unknown[] };
  };
  if (!response.ok) {
    const error = new Error(payload.error?.message ?? "discovery request failed");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

export const discoveryApiClient = {
  cityPreference(): Promise<CityPreference> {
    return discoveryApi<CityPreference>("/account/city-preference");
  },

  /**
   * Persist the member's city choice. Passing `city_code: null` clears the
   * preference and returns them to IP suggestions — it does not pin whatever
   * the IP happened to say at that moment.
   */
  setCityPreference(payload: {
    city_code: string | null;
    allow_ip_suggestion: boolean;
  }): Promise<CityPreference> {
    return discoveryApi<CityPreference>("/account/city-preference", {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },

  /**
   * `cityCode` here is a one-off override for this request only. It is
   * deliberately not persisted; that is what `setCityPreference` is for.
   */
  feed(params: { cityCode?: string | null; limit?: number; offset?: number } = {}): Promise<DiscoveryFeed> {
    const query = new URLSearchParams();
    if (params.cityCode) query.set("city_code", params.cityCode);
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return discoveryApi<DiscoveryFeed>(`/account/discovery/feed${suffix}`);
  },

  venueLocation(activityId: string): Promise<VenueLocation> {
    return discoveryApi<VenueLocation>(`/account/activities/${activityId}/venue-location`);
  },

  shareCard(activityId: string): Promise<ShareCard> {
    return discoveryApi<ShareCard>(`/account/activities/${activityId}/share-card`);
  }
};
