import { computed, ref } from "vue";

import { discoveryApiClient } from "@/features/discovery/api";
import type { CityPreference, DiscoveryFeed, DiscoveryItem } from "@/features/discovery/types";

export function useDiscoveryFeed() {
  const feed = ref<DiscoveryFeed | null>(null);
  const preference = ref<CityPreference | null>(null);
  const items = ref<DiscoveryItem[]>([]);
  const loading = ref(false);
  const saving = ref(false);
  const error = ref<string | null>(null);
  const errorCode = ref<string | null>(null);
  const pageSize = 20;

  /**
   * True when the server used an IP hint the member has not confirmed.
   *
   * This is the case the UI must not paper over: the results are already
   * filtered to a city nobody chose, so the member has to be told which city
   * and offered a one-tap correction.
   */
  const showsUnconfirmedCity = computed(
    () => Boolean(feed.value) && feed.value!.city_source === "ip_suggestion" && !feed.value!.city_is_confirmed
  );

  /** A different city the IP suggests, worth offering as a switch. */
  const suggestedSwitch = computed(() => {
    const current = feed.value;
    if (!current?.suggested_city_code) return null;
    if (current.suggested_city_code === current.city_code) return null;
    return current.suggested_city_code;
  });

  /** The filter stopped filtering. GEO-001 requires saying so, and why. */
  const fellBackToNational = computed(
    () => Boolean(feed.value?.fallback_applied) && feed.value?.scope === "national"
  );

  const hasMore = computed(() => items.value.length > 0 && items.value.length % pageSize === 0);

  async function load(cityOverride?: string | null) {
    loading.value = true;
    error.value = null;
    errorCode.value = null;
    try {
      const [result, pref] = await Promise.all([
        discoveryApiClient.feed({ cityCode: cityOverride ?? undefined, limit: pageSize, offset: 0 }),
        // A missing preference must not blank the feed; it only removes the
        // "this is your saved city" affordance.
        discoveryApiClient.cityPreference().catch(() => null)
      ]);
      feed.value = result;
      items.value = result.items;
      preference.value = pref;
    } catch (caught) {
      error.value = (caught as Error).message;
      errorCode.value = (caught as Error & { code?: string }).code ?? null;
    } finally {
      loading.value = false;
    }
  }

  async function loadMore(cityOverride?: string | null) {
    if (!feed.value) return;
    try {
      const next = await discoveryApiClient.feed({
        cityCode: cityOverride ?? undefined,
        limit: pageSize,
        offset: items.value.length
      });
      items.value = [...items.value, ...next.items];
    } catch (caught) {
      error.value = (caught as Error).message;
      errorCode.value = (caught as Error & { code?: string }).code ?? null;
    }
  }

  /** Confirm a city as the member's saved preference, then refresh. */
  async function confirmCity(cityCode: string | null) {
    saving.value = true;
    error.value = null;
    try {
      preference.value = await discoveryApiClient.setCityPreference({
        city_code: cityCode,
        allow_ip_suggestion: preference.value?.allow_ip_suggestion ?? true
      });
      await load();
    } catch (caught) {
      error.value = (caught as Error).message;
      errorCode.value = (caught as Error & { code?: string }).code ?? null;
    } finally {
      saving.value = false;
    }
  }

  async function setIpSuggestionAllowed(allowed: boolean) {
    saving.value = true;
    try {
      preference.value = await discoveryApiClient.setCityPreference({
        city_code: preference.value?.city_code ?? null,
        allow_ip_suggestion: allowed
      });
      await load();
    } catch (caught) {
      error.value = (caught as Error).message;
      errorCode.value = (caught as Error & { code?: string }).code ?? null;
    } finally {
      saving.value = false;
    }
  }

  return {
    feed,
    preference,
    items,
    loading,
    saving,
    error,
    errorCode,
    showsUnconfirmedCity,
    suggestedSwitch,
    fellBackToNational,
    hasMore,
    load,
    loadMore,
    confirmCity,
    setIpSuggestionAllowed
  };
}
