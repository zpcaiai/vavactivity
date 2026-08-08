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
};

export const processApi = {
  dashboard: () => catalogApi<ProcessRow>("/admin/processes/dashboard"),
  list: (section: string) => catalogApi<ProcessRow[]>(`/admin/processes/${encodeURIComponent(section)}`),
  verifyMachines: () => catalogApi<{ status: string; results: ProcessRow[] }>("/admin/processes/state-machines/verify", { method: "POST" }),
  scanStuck: () => catalogApi<{ created: number }>("/admin/processes/stuck/scan", { method: "POST" })
};
