import { catalogApi } from "@/features/catalog/api";

const base = "/admin/system";
export type SystemAdminRow = Record<string, unknown> & {
  id?: string;
  flag_code?: string;
  status?: string;
};

const aliases: Record<string, string> = {
  capacity: "capacity-baselines"
};

export const systemAdminApi = {
  view: (section: string) =>
    catalogApi<SystemAdminRow[] | SystemAdminRow>(
      `${base}/${encodeURIComponent(aliases[section] ?? section)}`
    ),
  createFlag: (payload: Record<string, unknown>) =>
    catalogApi<SystemAdminRow>(`${base}/feature-flags`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  approveFlag: (id: string) =>
    catalogApi<SystemAdminRow>(`${base}/feature-flags/${encodeURIComponent(id)}/approve`, {
      method: "POST"
    }),
  activateFlag: (id: string) =>
    catalogApi<SystemAdminRow>(`${base}/feature-flags/${encodeURIComponent(id)}/activate`, {
      method: "POST"
    }),
  changeMaintenance: (enabled: boolean, payload: Record<string, unknown>) =>
    catalogApi<SystemAdminRow>(`${base}/maintenance/${enabled ? "enable" : "disable"}`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  updateFlag: (id: string, payload: Record<string, unknown>) =>
    catalogApi<SystemAdminRow>(`${base}/feature-flags/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),

  approveRelease: (id: string) =>
    catalogApi<SystemAdminRow>(`${base}/releases/${encodeURIComponent(id)}/approve`, {
      method: "POST"
    }),

  rollbackRelease: (id: string, reasonCode: string) =>
    catalogApi<SystemAdminRow>(`${base}/releases/${encodeURIComponent(id)}/rollback`, {
      method: "POST",
      body: JSON.stringify({ reason_code: reasonCode })
    }),

  /** `retry` and `cancel` are the two operations the backend authorises. */
  operateJob: (id: string, operation: "retry" | "cancel", reasonCode: string) =>
    catalogApi<SystemAdminRow>(
      `${base}/jobs/${encodeURIComponent(id)}/${operation}`,
      { method: "POST", body: JSON.stringify({ reason_code: reasonCode }) }
    ),

  replayDeadLetter: (id: string, reasonCode: string) =>
    catalogApi<SystemAdminRow>(`${base}/dead-letters/${encodeURIComponent(id)}/replay`, {
      method: "POST",
      body: JSON.stringify({ reason_code: reasonCode })
    })
};

/**
 * Deliberately absent: creating a release record, recording a deployment,
 * backups, restore drills and capacity baselines. Those payloads are pipeline
 * receipts — image digests for four services, contract checksums, artifact
 * SHA-256, verification manifests. An operator typing them into a form would be
 * manufacturing the evidence the release gate is supposed to check.
 */
