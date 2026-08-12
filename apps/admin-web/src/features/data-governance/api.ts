import { catalogApi } from "@/features/catalog/api";

export type DataGovernanceRow = Record<string, unknown> & {
  id?: string;
  status?: string;
  asset_code?: string;
  contract_code?: string;
  event_type?: string;
  gap_code?: string;
  reconciliation_code?: string;
  backfill_code?: string;
  repair_code?: string;
  business_domain?: string;
};

export type BackfillAction =
  | "approve"
  | "start"
  | "pause"
  | "resume"
  | "complete"
  | "fail"
  | "cancel";

const BASE = "/admin/data-governance";

function operationKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

/**
 * Deliberately absent: `events/outbox`, `events/inbox`, `reconciliations/run`,
 * `quality/evaluate`, `backfills` (create) and `certifications/evaluate`. Those
 * endpoints take machine-produced evidence — payload hashes, comparison sets,
 * evaluated/failed record counts — that an operator cannot honestly type into a
 * form. They belong to the pipelines that compute the evidence; the console
 * governs what the pipelines produce.
 */
export const dataGovernanceApi = {
  dashboard: () => catalogApi<DataGovernanceRow>(`${BASE}/dashboard`),
  list: (section: string) => catalogApi<DataGovernanceRow[]>(`${BASE}/${encodeURIComponent(section)}`),

  registerExternalIdentifier: (payload: {
    entity_type: string;
    canonical_entity_id: string;
    provider_code: string;
    external_identifier: string;
  }) =>
    catalogApi<DataGovernanceRow>(`${BASE}/external-identifiers`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  actOnBackfill: (
    runId: string,
    action: BackfillAction,
    progress: { processed_delta?: number; success_delta?: number; failure_delta?: number } = {}
  ) =>
    catalogApi<DataGovernanceRow>(`${BASE}/backfills/${encodeURIComponent(runId)}/action`, {
      method: "POST",
      body: JSON.stringify({
        action,
        processed_delta: progress.processed_delta ?? 0,
        success_delta: progress.success_delta ?? 0,
        failure_delta: progress.failure_delta ?? 0
      })
    }),

  rebuildProjection: (payload: {
    asset_code: string;
    scope: "entity" | "partition" | "full";
    scope_key: string | null;
    source_checkpoint: Record<string, unknown>;
    shadow_build: boolean;
  }) =>
    catalogApi<DataGovernanceRow>(`${BASE}/projections/rebuild`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  requestRepair: (payload: {
    repair_code: string;
    reconciliation_difference_id: string | null;
    input_mapping: Record<string, unknown>;
  }) =>
    catalogApi<DataGovernanceRow>(`${BASE}/repairs`, {
      method: "POST",
      body: JSON.stringify({ ...payload, idempotency_key: operationKey("repair") })
    }),

  createErasurePlan: (payload: {
    privacy_request_id: string;
    subject_user_id: string;
    lineage_release_version: string;
  }) =>
    catalogApi<DataGovernanceRow>(`${BASE}/erasures/plans`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  issueErasureCertificate: (planId: string) =>
    catalogApi<DataGovernanceRow>(
      `${BASE}/erasures/plans/${encodeURIComponent(planId)}/certificate`,
      { method: "POST" }
    ),

  decideCertification: (
    certificationId: string,
    decision: "certified" | "rejected",
    reason: string
  ) =>
    catalogApi<DataGovernanceRow>(
      `${BASE}/certifications/${encodeURIComponent(certificationId)}/decide`,
      { method: "POST", body: JSON.stringify({ decision, reason }) }
    )
};
