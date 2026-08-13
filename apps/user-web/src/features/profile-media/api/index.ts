import { resolveApiBaseUrl } from "@/config/api";
import type {
  MediaGrant,
  MediaKind,
  ProfileMediaView,
  ProfileShareCard,
  ShareConsent,
  UploadTarget
} from "@/features/profile-media/types";
import { useAuthStore } from "@/stores/auth";

const baseUrl = resolveApiBaseUrl();

export async function profileMediaApi<T>(path: string, init: RequestInit = {}): Promise<T> {
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
    const error = new Error(payload.error?.message ?? "profile media request failed");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

export const profileMediaApiClient = {
  media(): Promise<ProfileMediaView> {
    return profileMediaApi<ProfileMediaView>("/account/profile-media");
  },

  /**
   * Declare an intended upload and receive a storage target. The declared size
   * and type only let the server reject an impossible upload early — the real
   * check happens at `finalize` against the bytes that actually landed.
   */
  registerUpload(payload: {
    kind: MediaKind;
    mime_type: string;
    byte_size: number;
    duration_seconds?: number | null;
    position?: number | null;
  }): Promise<UploadTarget> {
    return profileMediaApi<UploadTarget>("/account/profile-media/uploads", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  finalize(
    assetId: string,
    payload: { byte_size: number; mime_type: string; duration_seconds?: number | null }
  ): Promise<ProfileMediaView> {
    return profileMediaApi<ProfileMediaView>(
      `/account/profile-media/assets/${assetId}/finalize`,
      { method: "POST", body: JSON.stringify(payload) }
    );
  },

  replace(
    assetId: string,
    payload: { kind: MediaKind; mime_type: string; byte_size: number; duration_seconds?: number | null }
  ): Promise<ProfileMediaView> {
    return profileMediaApi<ProfileMediaView>(`/account/profile-media/assets/${assetId}`, {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },

  remove(assetId: string): Promise<ProfileMediaView> {
    return profileMediaApi<ProfileMediaView>(`/account/profile-media/assets/${assetId}`, {
      method: "DELETE"
    });
  },

  /** Short-lived signed grant for one private asset, bound to one viewer. */
  grant(assetId: string, ttlSeconds = 300): Promise<MediaGrant> {
    return profileMediaApi<MediaGrant>(
      `/account/profile-media/assets/${assetId}/access-grants`,
      { method: "POST", body: JSON.stringify({ ttl_seconds: ttlSeconds }) }
    );
  },

  setTags(payload: {
    mbti?: string | null;
    intro?: string | null;
    city_code?: string | null;
  }): Promise<ProfileMediaView> {
    return profileMediaApi<ProfileMediaView>("/account/profile-media/tags", {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },

  shareConsent(): Promise<ShareConsent> {
    return profileMediaApi<ShareConsent>("/account/profile-media/share-consent");
  },

  setShareConsent(payload: ShareConsent): Promise<ShareConsent> {
    return profileMediaApi<ShareConsent>("/account/profile-media/share-consent", {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },

  shareCard(): Promise<ProfileShareCard> {
    return profileMediaApi<ProfileShareCard>("/account/profile-media/share-card");
  }
};
