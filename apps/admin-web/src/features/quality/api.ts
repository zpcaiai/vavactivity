import { catalogApi } from "@/features/catalog/api";

export type QualityRow = Record<string, unknown> & {
  id?: string;
  status?: string;
  decision?: string;
  requirement_code?: string;
  capability_code?: string;
  gap_code?: string;
  gate_code?: string;
  release_version?: string;
};

export const qualityAdminApi = {
  dashboard: () => catalogApi<QualityRow>("/admin/quality/dashboard"),
  list: (section: string) =>
    catalogApi<QualityRow[]>(`/admin/quality/${encodeURIComponent(section)}`),
  transitionRequirement: (id: string, targetStatus: string) =>
    catalogApi<QualityRow>(`/admin/quality/requirements/${encodeURIComponent(id)}/transition`, {
      method: "POST",
      body: JSON.stringify({ target_status: targetStatus })
    }),
  resolveGap: (id: string) =>
    catalogApi<QualityRow>(`/admin/quality/gaps/${encodeURIComponent(id)}/resolve`, {
      method: "POST",
      body: JSON.stringify({ resolution_summary: "Verified by the quality operator after remediation and rescan." })
    }),
  decideWaiver: (id: string, action: "approve" | "revoke") =>
    catalogApi<QualityRow>(`/admin/quality/waivers/${encodeURIComponent(id)}/${action}`, {
      method: "POST"
    }),
  transitionEvidence: (id: string, action: "validate" | "accept") =>
    catalogApi<QualityRow>(`/admin/quality/evidence/${encodeURIComponent(id)}/${action}`, {
      method: "POST"
    }),
  approveGate: (id: string) =>
    catalogApi<QualityRow>(`/admin/quality/gates/${encodeURIComponent(id)}/approve`, {
      method: "POST"
    })
};
