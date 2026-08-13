import { resolveApiBaseUrl } from "@/config/api";
import type {
  AttendeePreview,
  FollowEdge,
  FollowResult,
  PreviewConsent,
  PreviewConsentState,
  SocialNotificationPreferences,
  WantToMeetResult
} from "@/features/attendee-social/types";
import { useAuthStore } from "@/stores/auth";

const baseUrl = resolveApiBaseUrl();

export async function socialApi<T>(path: string, init: RequestInit = {}): Promise<T> {
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
    const error = new Error(payload.error?.message ?? "social request failed");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

export const socialApiClient = {
  attendeePreview(
    activityId: string,
    params: { limit?: number; excludeAbsent?: boolean } = {}
  ): Promise<AttendeePreview> {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.excludeAbsent !== undefined) query.set("exclude_absent", String(params.excludeAbsent));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return socialApi<AttendeePreview>(`/account/activities/${activityId}/attendee-preview${suffix}`);
  },

  consent(registrationId: string): Promise<PreviewConsent> {
    return socialApi<PreviewConsent>(`/account/registrations/${registrationId}/preview-consent`);
  },

  /**
   * The decision is always explicit. There is no default on the wire because
   * an omitted field must never be readable as consent.
   */
  setConsent(
    registrationId: string,
    payload: { decision: Exclude<PreviewConsentState, "not_asked">; note?: string | null }
  ): Promise<PreviewConsent> {
    return socialApi<PreviewConsent>(`/account/registrations/${registrationId}/preview-consent`, {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },

  setIntro(registrationId: string, introLine: string | null): Promise<PreviewConsent> {
    return socialApi<PreviewConsent>(`/account/registrations/${registrationId}/preview-intro`, {
      method: "PUT",
      body: JSON.stringify({ intro_line: introLine })
    });
  },

  follow(userId: string): Promise<FollowResult> {
    return socialApi<FollowResult>("/account/follows", {
      method: "POST",
      body: JSON.stringify({ user_id: userId })
    });
  },

  unfollow(userId: string): Promise<FollowResult> {
    return socialApi<FollowResult>(`/account/follows/${userId}`, { method: "DELETE" });
  },

  following(limit = 50): Promise<{ items: FollowEdge[] }> {
    return socialApi<{ items: FollowEdge[] }>(`/account/follows/following?limit=${limit}`);
  },

  followers(limit = 50): Promise<{ items: FollowEdge[] }> {
    return socialApi<{ items: FollowEdge[] }>(`/account/follows/followers?limit=${limit}`);
  },

  /** Event-scoped intent. Distinct from a follow and from a like. */
  wantToMeet(userId: string, activityId: string): Promise<WantToMeetResult> {
    return socialApi<WantToMeetResult>("/account/want-to-meet", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, activity_id: activityId })
    });
  },

  notificationPreferences(): Promise<SocialNotificationPreferences> {
    return socialApi<SocialNotificationPreferences>("/account/social/notification-preferences");
  },

  setNotificationPreferences(
    payload: SocialNotificationPreferences
  ): Promise<SocialNotificationPreferences> {
    return socialApi<SocialNotificationPreferences>("/account/social/notification-preferences", {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  }
};
