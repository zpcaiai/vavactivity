import { catalogApi } from "@/features/catalog/api";

export type ProcessRow = Record<string, unknown> & {
  id?: string;
  status?: string;
  process_code?: string;
  process_number?: string;
  machine_code?: string;
  finding_code?: string;
  scenario_code?: string;
  business_domain?: string;
  lock_version?: number;
  allowed_resolution_commands?: string[];
};

export type ProcessInstanceDetail = {
  instance: ProcessRow;
  steps: ProcessRow[];
  compensations: ProcessRow[];
};

/**
 * A single random key is enough for both idempotency and cancellation keys:
 * the backend only requires 8-255 characters and uses it to collapse retries.
 */
function operationKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

export const processApi = {
  dashboard: () => catalogApi<ProcessRow>("/admin/processes/dashboard"),
  list: (section: string) => catalogApi<ProcessRow[]>(`/admin/processes/${encodeURIComponent(section)}`),
  instance: (instanceId: string) =>
    catalogApi<ProcessInstanceDetail>(`/admin/processes/instances/${encodeURIComponent(instanceId)}`),
  verifyMachines: () => catalogApi<{ status: string; results: ProcessRow[] }>("/admin/processes/state-machines/verify", { method: "POST" }),
  scanStuck: () => catalogApi<{ created: number }>("/admin/processes/stuck/scan", { method: "POST" }),

  /**
   * The backend rejects any command that is not in the task's own
   * `allowed_resolution_commands`, so the caller must pass one of those.
   */
  resolveIntervention: (taskId: string, resolutionCommand: string, note: string) =>
    catalogApi<ProcessRow>(`/admin/processes/interventions/${encodeURIComponent(taskId)}/resolve`, {
      method: "POST",
      body: JSON.stringify({
        resolution_command: resolutionCommand,
        receipt: { note, resolved_via: "admin_console" }
      })
    }),

  cancelInstance: (
    instanceId: string,
    payload: { request_type: string; reason_code: string; expected_lock_version: number }
  ) =>
    catalogApi<ProcessRow>(`/admin/processes/instances/${encodeURIComponent(instanceId)}/cancel`, {
      method: "POST",
      body: JSON.stringify({ ...payload, cancellation_key: operationKey("cancel") })
    }),

  requestCompensation: (instanceId: string, stepExecutionId: string, compensationCode: string) =>
    catalogApi<ProcessRow>(
      `/admin/processes/instances/${encodeURIComponent(instanceId)}/compensations`,
      {
        method: "POST",
        body: JSON.stringify({
          step_execution_id: stepExecutionId,
          compensation_code: compensationCode,
          idempotency_key: operationKey("compensate")
        })
      }
    ),

  decideCertification: (certificationId: string, decision: "certified" | "rejected", reason: string) =>
    catalogApi<ProcessRow>(
      `/admin/processes/certifications/${encodeURIComponent(certificationId)}/decide`,
      { method: "POST", body: JSON.stringify({ decision, reason }) }
    ),

  runSimulation: (scenarioCode: string, syntheticSeed: number) =>
    catalogApi<ProcessRow>("/admin/processes/simulations", {
      method: "POST",
      body: JSON.stringify({ scenario_code: scenarioCode, synthetic_seed: syntheticSeed })
    })
};
