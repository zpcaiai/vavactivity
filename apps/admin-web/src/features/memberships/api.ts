import { catalogApi } from "@/features/catalog/api";

const base = "/admin/memberships";
export type MembershipAdminRow = Record<string, unknown> & { id?: string; status?: string };

function operationKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

/**
 * Note on plan versions, SKU mappings and trial policies: the backend exposes
 * create and lifecycle endpoints for all three but no list endpoint, so the
 * console cannot enumerate their ids. Creation returns the new row, which is
 * why the page keeps what it just created in view and also accepts a pasted id.
 */
export const membershipAdminApi = {
  dashboard: () => catalogApi<Record<string, unknown>>(`${base}/dashboard`),
  plans: () => catalogApi<MembershipAdminRow[]>(`${base}/plans`),
  plan: (planId: string) => catalogApi<MembershipAdminRow>(`${base}/plans/${encodeURIComponent(planId)}`),
  benefits: () => catalogApi<MembershipAdminRow[]>(`${base}/benefits`),
  reconciliation: () => catalogApi<MembershipAdminRow[]>(`${base}/reconciliation`),
  resource: (name: string) => catalogApi<MembershipAdminRow[]>(`${base}/${encodeURIComponent(name)}`),

  resolveIssue: (id: string, summary: string) =>
    catalogApi<MembershipAdminRow>(`${base}/reconciliation/${encodeURIComponent(id)}/resolve`, {
      method: "POST",
      body: JSON.stringify({ resolution_summary: summary })
    }),

  createPlan: (payload: Record<string, unknown>) =>
    catalogApi<MembershipAdminRow>(`${base}/plans`, { method: "POST", body: JSON.stringify(payload) }),

  updatePlan: (planId: string, payload: Record<string, unknown>) =>
    catalogApi<MembershipAdminRow>(`${base}/plans/${encodeURIComponent(planId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),

  createPlanVersion: (planId: string, payload: Record<string, unknown>) =>
    catalogApi<MembershipAdminRow>(`${base}/plans/${encodeURIComponent(planId)}/versions`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  /** Draft → review → approved → active → retired, one step per call. */
  transitionVersion: (
    versionId: string,
    action: "submit-review" | "approve" | "activate" | "retire"
  ) =>
    catalogApi<MembershipAdminRow>(
      `${base}/membership-plan-versions/${encodeURIComponent(versionId)}/${action}`,
      { method: "POST", body: JSON.stringify({}) }
    ),

  createBenefit: (payload: Record<string, unknown>) =>
    catalogApi<MembershipAdminRow>(`${base}/benefits`, { method: "POST", body: JSON.stringify(payload) }),

  createSkuMapping: (payload: Record<string, unknown>) =>
    catalogApi<MembershipAdminRow>(`${base}/sku-mappings`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  adjustQuota: (
    bucketId: string,
    payload: { quantity: number; adjustment_type: string; reason_code: string; reason: string }
  ) =>
    catalogApi<MembershipAdminRow>(
      `${base}/quota-buckets/${encodeURIComponent(bucketId)}/adjustments`,
      { method: "POST", body: JSON.stringify({ ...payload, idempotency_key: operationKey("quota") }) }
    ),

  createManualGrant: (payload: Record<string, unknown>) =>
    catalogApi<MembershipAdminRow>(`${base}/manual-grants`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  decideManualGrant: (grantId: string, action: "approve" | "revoke") =>
    catalogApi<MembershipAdminRow>(
      `${base}/manual-grants/${encodeURIComponent(grantId)}/${action}`,
      { method: "POST", body: JSON.stringify({}) }
    ),

  createTrialPolicy: (payload: Record<string, unknown>) =>
    catalogApi<MembershipAdminRow>(`${base}/trials`, { method: "POST", body: JSON.stringify(payload) })
};
