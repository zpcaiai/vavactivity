import { catalogApi } from "@/features/catalog/api";

export type AdminPlatformRow = Record<string, unknown> & { id?: string; status?: string };

export const adminPlatformApi = {
  dashboard: () => catalogApi<AdminPlatformRow>("/admin/platform/dashboard"),
  list: (section: string) => catalogApi<AdminPlatformRow[]>(`/admin/platform/${encodeURIComponent(section)}`)
};
