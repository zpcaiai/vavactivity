import { catalogApi } from "@/features/catalog/api";

const base = "/admin/trust-safety";
export type SafetyAdminRow = Record<string, unknown> & { id?: string; status?: string };

export const safetyAdminApi = {
  queue: (section: string) =>
    catalogApi<SafetyAdminRow[]>(`${base}/${encodeURIComponent(section)}`),
  transitionCase: (id: string, targetStatus: string) =>
    catalogApi<SafetyAdminRow>(`${base}/cases/${encodeURIComponent(id)}/transition`, {
      method: "POST",
      body: JSON.stringify({ target_status: targetStatus })
    }),
  decideModeration: (id: string, payload: Record<string, unknown>) =>
    catalogApi<SafetyAdminRow>(`${base}/moderation/${encodeURIComponent(id)}/decisions`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  decideAppeal: (id: string, payload: Record<string, unknown>) =>
    catalogApi<SafetyAdminRow>(`${base}/appeals/${encodeURIComponent(id)}/decision`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  activateRule: (id: string) =>
    catalogApi<SafetyAdminRow>(`${base}/rules/${encodeURIComponent(id)}/activate`, {
      method: "POST"
    })
};
