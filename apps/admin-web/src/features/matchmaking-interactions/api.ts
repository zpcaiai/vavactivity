import { catalogApi } from "@/features/catalog/api";

const BASE = "/admin/matchmaking/interactions";

export type InteractionAdminRow = Record<string, unknown> & {
  id?: string;
  pair_id?: string;
  mutual_match_id?: string;
  status?: string;
};

export const matchmakingInteractionAdminApi = {
  dashboard: () => catalogApi<Record<string, unknown>>(`${BASE}/dashboard`),
  pairs: () => catalogApi<InteractionAdminRow[]>(`${BASE}/pairs`),
  pair: (pairId: string) =>
    catalogApi<Record<string, unknown>>(`${BASE}/pairs/${encodeURIComponent(pairId)}`),
  matches: () => catalogApi<InteractionAdminRow[]>(`${BASE}/matches`),
  invitations: () => catalogApi<InteractionAdminRow[]>(`${BASE}/invitations`),
  contactExchanges: () =>
    catalogApi<InteractionAdminRow[]>(`${BASE}/contact-exchanges`),
  contactExchange: (exchangeId: string) =>
    catalogApi<Record<string, unknown>>(
      `${BASE}/contact-exchanges/${encodeURIComponent(exchangeId)}`
    ),
  invalidations: () => catalogApi<InteractionAdminRow[]>(`${BASE}/invalidations`),
  deadLetters: () => catalogApi<InteractionAdminRow[]>(`${BASE}/dead-letters`),
  incidents: () =>
    catalogApi<{ incidents: InteractionAdminRow[]; boundary: string }>(`${BASE}/incidents`),
  audit: () => catalogApi<InteractionAdminRow[]>(`${BASE}/audit`),
  duplicates: () => catalogApi<Record<string, number>>(`${BASE}/diagnostics/duplicates`),
  invalidatePair: (pairId: string, reasonCode: string, purpose: string) =>
    catalogApi<Record<string, unknown>>(`${BASE}/pairs/${encodeURIComponent(pairId)}/invalidate`, {
      method: "POST",
      body: JSON.stringify({ reason_code: reasonCode, purpose })
    }),
  revokeContactExchange: (exchangeId: string, reasonCode: string, purpose: string) =>
    catalogApi<Record<string, unknown>>(
      `${BASE}/contact-exchanges/${encodeURIComponent(exchangeId)}/revoke`,
      { method: "POST", body: JSON.stringify({ reason_code: reasonCode, purpose }) }
    ),
  resolveDeadLetter: (deadLetterId: string, note: string) =>
    catalogApi<Record<string, unknown>>(
      `${BASE}/dead-letters/${encodeURIComponent(deadLetterId)}/resolve`,
      { method: "POST", body: JSON.stringify({ purpose: note }) }
    )
};
