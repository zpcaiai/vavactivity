import { catalogApi } from "@/features/catalog/api";

export type DesignRow = Record<string, unknown> & {
  id?: string;
  status?: string;
  token_version?: string;
  component_code?: string;
  pattern_code?: string;
  audit_code?: string;
  baseline_code?: string;
  route_path?: string;
};

export const designSystemAdminApi = {
  dashboard: () => catalogApi<DesignRow>("/admin/design-system/dashboard"),
  list: async (section: string) => {
    const value = await catalogApi<DesignRow[] | { runs: DesignRow[]; differences: DesignRow[] }>(
      `/admin/design-system/${encodeURIComponent(section)}`
    );
    return Array.isArray(value)
      ? value
      : [
          ...value.runs.map((row) => ({ ...row, record_kind: "audit_run" })),
          ...value.differences.map((row) => ({ ...row, record_kind: "visual_difference" }))
        ];
  },
  approveToken: (id: string) =>
    catalogApi<DesignRow>(`/admin/design-system/tokens/${encodeURIComponent(id)}/approve`, {
      method: "POST"
    }),
  decideBaseline: (id: string, decision: "approve" | "reject") =>
    catalogApi<DesignRow>(`/admin/design-system/baselines/${encodeURIComponent(id)}/decision`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        reason: "Reviewed against the approved page matrix and synthetic fixture policy."
      })
    }),
  reviewAudit: (id: string, decision: "approve" | "reject", accessibility = false) =>
    catalogApi<DesignRow>(
      accessibility
        ? `/admin/design-system/accessibility/${encodeURIComponent(id)}/review`
        : `/admin/design-system/audits/${encodeURIComponent(id)}/review`,
      {
        method: "POST",
        body: JSON.stringify({
          decision,
          reason: "Independent evidence review completed with keyboard and visual artifacts."
        })
      }
    ),
  acceptEvidence: (id: string) =>
    catalogApi<DesignRow>(`/admin/design-system/evidence/${encodeURIComponent(id)}/accept`, {
      method: "POST"
    })
};
