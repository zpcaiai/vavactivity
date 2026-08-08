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
    })
};
