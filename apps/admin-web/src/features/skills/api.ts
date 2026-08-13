import { catalogApi } from "@/features/catalog/api";

export type SkillRow = Record<string, unknown> & {
  id?: string;
  skill_name?: string;
  semantic_version?: string;
  status?: string;
  listing_status?: string;
  granted_permissions?: string[];
};

/**
 * Sections with no backend list endpoint. The console used to fill these tabs
 * with whatever other call was handy — the skill catalogue stood in for
 * dependencies, execution records stood in for security incidents and audit —
 * so operators were reading data from a different domain than the tab claimed.
 * Better an explicit empty state than a convincing wrong one.
 */
export const SKILL_SECTIONS_WITHOUT_SOURCE = ["dependencies", "configurations", "audit"];

export const skillsAdminApi = {
  catalog: () => catalogApi<SkillRow[]>("/skills"),
  versions: (skillName: string) =>
    catalogApi<SkillRow[]>(`/skills/${encodeURIComponent(skillName)}/versions`),
  installations: () => catalogApi<SkillRow[]>("/admin/skill-installations"),
  executions: () => catalogApi<SkillRow[]>("/admin/skill-executions"),
  marketplace: () => catalogApi<SkillRow[]>("/admin/skills/marketplace"),
  publishers: () => catalogApi<SkillRow[]>("/admin/skills/publishers"),
  incidents: () => catalogApi<SkillRow[]>("/admin/skills/incidents"),
  installation: (id: string) =>
    catalogApi<SkillRow>(`/admin/skill-installations/${encodeURIComponent(id)}`),
  execution: (id: string) =>
    catalogApi<SkillRow>(`/admin/skill-executions/${encodeURIComponent(id)}`),

  approveInstallation: (id: string) =>
    catalogApi<SkillRow>(`/admin/skill-installations/${encodeURIComponent(id)}/approve`, {
      method: "POST"
    }),
  activateInstallation: (id: string) =>
    catalogApi<SkillRow>(`/admin/skill-installations/${encodeURIComponent(id)}/activate`, {
      method: "POST"
    }),
  disableInstallation: (id: string, reasonCode: string) =>
    catalogApi<SkillRow>(`/admin/skill-installations/${encodeURIComponent(id)}/disable`, {
      method: "POST",
      body: JSON.stringify({ reason_code: reasonCode })
    }),
  rollbackInstallation: (id: string, reasonCode: string) =>
    catalogApi<SkillRow>(`/admin/skill-installations/${encodeURIComponent(id)}/rollback`, {
      method: "POST",
      body: JSON.stringify({ reason_code: reasonCode })
    }),
  uninstallInstallation: (id: string, reasonCode: string) =>
    catalogApi<SkillRow>(`/admin/skill-installations/${encodeURIComponent(id)}/uninstall`, {
      method: "POST",
      body: JSON.stringify({ reason_code: reasonCode })
    }),

  cancelExecution: (id: string) =>
    catalogApi<SkillRow>(`/admin/skill-executions/${encodeURIComponent(id)}/cancel`, {
      method: "POST"
    }),

  reviewListing: (id: string, decision: "approved" | "changes_required", reasonCode: string, findings: string[]) =>
    catalogApi<SkillRow>(`/admin/skills/marketplace/${encodeURIComponent(id)}/review`, {
      method: "POST",
      body: JSON.stringify({ decision, reason_code: reasonCode, findings })
    }),
  publishListing: (id: string) =>
    catalogApi<SkillRow>(`/admin/skills/marketplace/${encodeURIComponent(id)}/publish`, {
      method: "POST"
    }),

  verifyPublisher: (id: string, decision: "verified" | "rejected", reasonCode: string) =>
    catalogApi<SkillRow>(`/admin/skills/publishers/${encodeURIComponent(id)}/verify`, {
      method: "POST",
      body: JSON.stringify({ decision, reason_code: reasonCode })
    }),

  /** Supply-chain gates. Reason codes are SCREAMING_SNAKE per the backend pattern. */
  securityReview: (
    versionId: string,
    payload: { decision: "passed" | "passed_with_warnings" | "failed"; compatible: boolean; reason_code: string; report: Record<string, unknown> }
  ) =>
    catalogApi<SkillRow>(
      `/admin/skills/registry/versions/${encodeURIComponent(versionId)}/security-review`,
      { method: "POST", body: JSON.stringify(payload) }
    ),
  quarantineVersion: (versionId: string, reasonCode: string) =>
    catalogApi<SkillRow>(
      `/admin/skills/registry/versions/${encodeURIComponent(versionId)}/quarantine`,
      { method: "POST", body: JSON.stringify({ reason_code: reasonCode }) }
    ),
  revokeSignature: (payload: {
    publisher_id: string;
    key_id: string;
    package_checksum: string | null;
    reason_code: string;
    reason: string;
  }) =>
    catalogApi<SkillRow>("/admin/skills/signature-revocations", {
      method: "POST",
      body: JSON.stringify(payload)
    })
};
