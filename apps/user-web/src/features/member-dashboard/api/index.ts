import { resolveApiBaseUrl } from "@/config/api";
import type {
  DashboardPreferences,
  DashboardSection,
  DashboardSectionKey,
  DashboardView,
  DismissalResult
} from "@/features/member-dashboard/types";
import { useAuthStore } from "@/stores/auth";

const baseUrl = resolveApiBaseUrl();

/**
 * Thin fetch wrapper for the dashboard endpoints.
 *
 * The server's error `code` is preserved on the thrown error so callers can
 * localize from the code; the English `message` is for operators and is never
 * rendered to a member.
 */
export async function dashboardApi<T>(path: string, init: RequestInit = {}): Promise<T> {
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
    const error = new Error(payload.error?.message ?? "dashboard request failed");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

export const dashboardApiClient = {
  /**
   * The aggregate view. Returns 200 even when a source module is down, with
   * the broken sections named in `degraded` — so a caller must not treat a
   * successful response as "everything loaded".
   */
  dashboard(params: { locale?: string; limit?: number; offset?: number } = {}): Promise<DashboardView> {
    const query = new URLSearchParams();
    if (params.locale) query.set("locale", params.locale);
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return dashboardApi<DashboardView>(`/account/dashboard${suffix}`);
  },

  /** Page one section on its own — backs the "show all" links. */
  section(
    section: DashboardSectionKey,
    params: { locale?: string; limit?: number; offset?: number } = {}
  ): Promise<DashboardSection> {
    const query = new URLSearchParams();
    if (params.locale) query.set("locale", params.locale);
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return dashboardApi<DashboardSection>(`/account/dashboard/sections/${section}${suffix}`);
  },

  preferences(): Promise<DashboardPreferences> {
    return dashboardApi<DashboardPreferences>("/account/dashboard/preferences");
  },

  savePreferences(payload: DashboardPreferences): Promise<DashboardPreferences> {
    return dashboardApi<DashboardPreferences>("/account/dashboard/preferences", {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },

  dismiss(payload: { task_type: string; task_key: string }): Promise<DismissalResult> {
    return dashboardApi<DismissalResult>("/account/dashboard/dismissals", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  restore(taskKey: string): Promise<DismissalResult> {
    return dashboardApi<DismissalResult>(
      `/account/dashboard/dismissals/${encodeURIComponent(taskKey)}`,
      { method: "DELETE" }
    );
  }
};
