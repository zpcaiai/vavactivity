import { computed, getCurrentScope, onScopeDispose, ref } from "vue";

import { profileMediaApiClient } from "@/features/profile-media/api";
import type { MediaAsset, MediaGrant } from "@/features/profile-media/types";

const REFRESH_LEAD_MS = 30_000;
const MEDIA_ERROR_RETRY_COOLDOWN_MS = 60_000;

/**
 * Maintains short-lived storage URLs for private profile media.
 *
 * The API authorizes the current viewer before issuing each URL. The URL itself
 * is bearer access, so the client keeps it only in memory, remembers its real
 * expiry, refreshes shortly before that expiry, and retries once when a sleeping
 * tab wakes up to an expired media request.
 */
export function useMediaGrants() {
  const grants = ref<Record<string, MediaGrant>>({});
  const refreshTimers = new Map<string, ReturnType<typeof setTimeout>>();
  const inFlight = new Map<string, Promise<void>>();
  const lastErrorRefreshAt = new Map<string, number>();

  const mediaUrls = computed<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(grants.value).map(([assetId, grant]) => [assetId, grant.media_url])
    )
  );

  function clearTimer(assetId: string) {
    const timer = refreshTimers.get(assetId);
    if (timer !== undefined) clearTimeout(timer);
    refreshTimers.delete(assetId);
  }

  function forget(assetId: string) {
    clearTimer(assetId);
    const next = { ...grants.value };
    delete next[assetId];
    grants.value = next;
  }

  function scheduleRefresh(assetId: string, expiresAt: string) {
    clearTimer(assetId);
    const expiry = Date.parse(expiresAt);
    if (!Number.isFinite(expiry)) return;
    const delay = Math.max(0, expiry - Date.now() - REFRESH_LEAD_MS);
    refreshTimers.set(
      assetId,
      setTimeout(() => {
        refreshTimers.delete(assetId);
        void refresh(assetId).catch(() => {
          // Keep the existing URL: the refresh runs before expiry, so it may
          // still be usable. If it later fails to load, the media error path
          // removes it and performs one explicit, cooldown-protected retry.
        });
      }, delay)
    );
  }

  function remember(assetId: string, grant: MediaGrant) {
    grants.value = { ...grants.value, [assetId]: grant };
    scheduleRefresh(assetId, grant.expires_at);
  }

  async function refresh(assetId: string): Promise<void> {
    const existing = inFlight.get(assetId);
    if (existing) return existing;
    const request = profileMediaApiClient
      .grant(assetId)
      .then((grant) => remember(assetId, grant))
      .finally(() => inFlight.delete(assetId));
    inFlight.set(assetId, request);
    return request;
  }

  async function load(assets: MediaAsset[]) {
    const wanted = new Set(assets.map((asset) => asset.asset_id));
    for (const assetId of Object.keys(grants.value)) {
      if (!wanted.has(assetId)) forget(assetId);
    }
    await Promise.allSettled(assets.map((asset) => refresh(asset.asset_id)));
  }

  async function refreshAfterMediaError(assetId: string) {
    const now = Date.now();
    const previous = lastErrorRefreshAt.get(assetId) ?? 0;
    forget(assetId);
    if (now - previous < MEDIA_ERROR_RETRY_COOLDOWN_MS) return;
    lastErrorRefreshAt.set(assetId, now);
    try {
      await refresh(assetId);
    } catch {
      // The page deliberately falls back to "preview unavailable". A later
      // explicit reload will request a fresh grant and surface page-level errors.
    }
  }

  function dispose() {
    for (const assetId of refreshTimers.keys()) clearTimer(assetId);
  }

  if (getCurrentScope()) onScopeDispose(dispose);

  return {
    grants,
    mediaUrls,
    loadMediaGrants: load,
    forgetMediaGrant: forget,
    refreshAfterMediaError,
    dispose
  };
}
