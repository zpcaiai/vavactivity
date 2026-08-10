import { catalogApi } from "@/features/catalog/api";

const BASE = "/admin/relationships";

export type RelationshipAdminRow = Record<string, unknown> & {
  journey_id?: string;
  status?: string;
};

export const relationshipAdminApi = {
  dashboard: () => catalogApi<Record<string, unknown>>(`${BASE}/dashboard`),
  journeys: () => catalogApi<RelationshipAdminRow[]>(BASE),
  journey: (id: string) => catalogApi<Record<string, unknown>>(`${BASE}/${encodeURIComponent(id)}`),
  freeze: (id: string, reasonCode: string, purpose: string) => catalogApi<RelationshipAdminRow>(`${BASE}/${encodeURIComponent(id)}/freeze`, { method: "POST", body: JSON.stringify({ reason_code: reasonCode, purpose }) }),
  unfreeze: (id: string, reasonCode: string, purpose: string) => catalogApi<RelationshipAdminRow>(`${BASE}/${encodeURIComponent(id)}/unfreeze`, { method: "POST", body: JSON.stringify({ reason_code: reasonCode, purpose }) }),
  endForSafety: (id: string, reasonCode: string, purpose: string) => catalogApi<RelationshipAdminRow>(`${BASE}/${encodeURIComponent(id)}/end-for-safety`, { method: "POST", body: JSON.stringify({ reason_code: reasonCode, purpose }) })
};
