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
  business_domain?: string;
};

export const dataGovernanceApi = {
  dashboard: () => catalogApi<DataGovernanceRow>("/admin/data-governance/dashboard"),
  list: (section: string) => catalogApi<DataGovernanceRow[]>(`/admin/data-governance/${encodeURIComponent(section)}`)
};
