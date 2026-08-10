import { catalogApi } from "@/features/catalog/api";

export type SkillRow = Record<string, unknown> & {
  id?: string;
  skill_name?: string;
  semantic_version?: string;
  status?: string;
  listing_status?: string;
  granted_permissions?: string[];
};

export const skillsAdminApi = {
  catalog: () => catalogApi<SkillRow[]>("/skills"),
  installations: () => catalogApi<SkillRow[]>("/admin/skill-installations"),
  executions: () => catalogApi<SkillRow[]>("/admin/skill-executions"),
  marketplace: () => catalogApi<SkillRow[]>("/admin/skills/marketplace"),
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
  disableInstallation: (id: string) =>
    catalogApi<SkillRow>(`/admin/skill-installations/${encodeURIComponent(id)}/disable`, {
      method: "POST",
      body: JSON.stringify({ reason_code: "OPERATOR_CONFIRMED" })
    }),
  cancelExecution: (id: string) =>
    catalogApi<SkillRow>(`/admin/skill-executions/${encodeURIComponent(id)}/cancel`, {
      method: "POST"
    }),
  reviewListing: (id: string, decision: "approved" | "changes_required") =>
    catalogApi<SkillRow>(`/admin/skills/marketplace/${encodeURIComponent(id)}/review`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        reason_code: decision === "approved" ? "REVIEW_PASSED" : "CHANGES_REQUIRED",
        findings: []
      })
    }),
  publishListing: (id: string) =>
    catalogApi<SkillRow>(`/admin/skills/marketplace/${encodeURIComponent(id)}/publish`, {
      method: "POST"
    })
};
