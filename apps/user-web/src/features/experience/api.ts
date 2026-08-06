import { useAuthStore } from "@/stores/auth";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export type ExperienceRow = Record<string, unknown> & {
  id?: string;
  route_code?: string;
  route_path?: string;
  task_code?: string;
  journey_code?: string;
  current_step_code?: string;
  state?: string;
  title?: string;
  title_i18n?: Record<string, string>;
  description_i18n?: Record<string, string>;
  action_route_code?: string;
  fallback_route_code?: string;
};

async function request<T>(path: string, init: RequestInit = {}, allowPublic = false): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, credentials: "include" });
  const payload = (await response.json()) as { data: T; error?: { message?: string; code?: string } };
  if (!response.ok) {
    if (allowPublic && response.status === 401) throw new Error("AUTH_REQUIRED");
    throw new Error(payload.error?.message ?? "体验服务请求失败");
  }
  return payload.data;
}

export const experienceApi = {
  home: () => request<ExperienceRow>("/experience/home"),
  tasks: (history = false) => request<ExperienceRow[]>(`/experience/tasks?include_history=${history}`),
  journeys: () => request<ExperienceRow[]>("/experience/journeys"),
  navigation: (locale: string) => request<{ items: ExperienceRow[] }>(`/experience/navigation?locale=${encodeURIComponent(locale)}`),
  publicNavigation: (locale: string) => request<{ items: ExperienceRow[] }>(`/public/experience/navigation?locale=${encodeURIComponent(locale)}`),
  search: (query: string, authenticated: boolean) => request<ExperienceRow[]>(`${authenticated ? "/experience" : "/public/experience"}/search?q=${encodeURIComponent(query)}`),
  help: (routeCode: string | undefined, locale: string, authenticated: boolean) => request<ExperienceRow[]>(`${authenticated ? "/experience" : "/public/experience"}/help?locale=${encodeURIComponent(locale)}${routeCode ? `&route_code=${encodeURIComponent(routeCode)}` : ""}`),
  feedback: (routeCode: string, feedbackType: string) => request<ExperienceRow>("/experience/feedback", { method: "POST", body: JSON.stringify({ route_code: routeCode, feedback_type: feedbackType, context: {} }) }),
  support: (payload: Record<string, unknown>) => request<ExperienceRow>("/experience/support", { method: "POST", body: JSON.stringify(payload) })
};
