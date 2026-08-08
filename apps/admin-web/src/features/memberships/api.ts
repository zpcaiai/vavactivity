import { catalogApi } from "@/features/catalog/api";

const base = "/admin/memberships";
export type MembershipAdminRow = Record<string, unknown> & { id?: string; status?: string };

export const membershipAdminApi = {
  dashboard: () => catalogApi<Record<string, unknown>>(`${base}/dashboard`),
  plans: () => catalogApi<MembershipAdminRow[]>(`${base}/plans`),
  benefits: () => catalogApi<MembershipAdminRow[]>(`${base}/benefits`),
  reconciliation: () => catalogApi<MembershipAdminRow[]>(`${base}/reconciliation`),
  resource: (name: string) => catalogApi<MembershipAdminRow[]>(`${base}/${encodeURIComponent(name)}`),
  resolveIssue: (id: string, summary: string) => catalogApi<MembershipAdminRow>(`${base}/reconciliation/${encodeURIComponent(id)}/resolve`, { method: "POST", body: JSON.stringify({ resolution_summary: summary }) }),
  createPlan: (payload: Record<string, unknown>) => catalogApi<MembershipAdminRow>(`${base}/plans`, { method: "POST", body: JSON.stringify(payload) })
};
