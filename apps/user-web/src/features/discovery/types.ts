/**
 * Discovery types (B13 GEO-001 / MAP-001 / SHARE-001).
 *
 * Three server-owned facts drive this UI and must never be re-derived here:
 *
 * - `city_source` says where the city came from. An IP hint is advisory and is
 *   never a confirmed preference, so the UI has to offer it rather than apply
 *   it silently.
 * - `fallback_reason` says *why* a query returned national results. GEO-001
 *   exists because a filter that silently stops filtering is indistinguishable
 *   from a broken one.
 * - `geocode_status` says whether an address was resolved. A failed geocode
 *   keeps the operator's typed address; the UI shows that address rather than
 *   pretending there is a pin.
 */

export type ResultScope = "local" | "national";

export type FallbackReason =
  | "not_applied"
  | "no_city_resolved"
  | "local_results_empty"
  | "local_below_minimum";

export type LocationSource = "manual" | "ip_suggestion" | "none";

export interface CityPreference {
  city_code: string | null;
  allow_ip_suggestion: boolean;
  confirmed_at: string | null;
}

export interface DiscoveryItem {
  id: string;
  title: string | null;
  starts_at: string;
  cover_image_url: string | null;
  city_code: string | null;
  display_address: string | null;
}

export interface DiscoveryFeed {
  scope: ResultScope;
  city_code: string | null;
  city_source: LocationSource;
  /** True only when the member picked the city themselves. */
  city_is_confirmed: boolean;
  /** What the IP hinted at, so the UI can offer "switch to X?". */
  suggested_city_code: string | null;
  fallback_applied: boolean;
  fallback_reason: FallbackReason;
  local_count: number;
  items: DiscoveryItem[];
}

export type GeocodeStatus = "resolved" | "failed" | "skipped";

export interface NormalizedPlace {
  formatted_address: string;
  country_code: string;
  region_code: string | null;
  city_code: string | null;
  latitude: number | null;
  longitude: number | null;
  provider: string;
  provider_place_ref: string | null;
}

export interface VenueLocation {
  /** Exactly what the operator typed. Never blanked by a failed geocode. */
  manual_address: string;
  display_address: string;
  geocode_status: GeocodeStatus;
  failure_code: string | null;
  place: NormalizedPlace | null;
  /** Server-built map link, or a search fallback when there is no pin. */
  display_link: string | null;
}

export interface ShareCardPayload {
  event_id: string;
  card_version: number;
  title: string;
  subtitle: string | null;
  city_code: string | null;
  starts_at: string;
  cover_image_url: string;
  cover_is_fallback: boolean;
  canonical_url: string;
}

export interface ShareCard {
  card: ShareCardPayload;
  /** Changes whenever the card content changes; safe as a cache key. */
  fingerprint: string;
  cover_is_fallback: boolean;
  short_code: string | null;
  canonical_url: string;
  qr_target: string;
}
