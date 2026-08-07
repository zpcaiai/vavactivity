import { catalogApi } from "@/features/catalog/api";

export type ExperienceAdminRow = Record<string, unknown> & {
  id?: string;
  status?: string;
  state?: string;
  route_code?: string;
  node_code?: string;
  task_code?: string;
  journey_code?: string;
  handoff_code?: string;
  article_code?: string;
  finding_code?: string;
  capability_code?: string;
};

export const experienceAdminApi = {
  dashboard: () => catalogApi<ExperienceAdminRow>("/admin/experience/dashboard"),
  list: (section: string) => {
    if (section === "navigation") return catalogApi<{ items: ExperienceAdminRow[] }>("/admin/experience/navigation").then((value) => value.items);
    if (section === "analytics") return catalogApi<{ events: ExperienceAdminRow[] }>("/admin/experience/analytics").then((value) => value.events);
    if (section === "audit") return catalogApi<ExperienceAdminRow[]>("/admin/experience/audit");
    if (section === "release") return catalogApi<ExperienceAdminRow[]>("/admin/experience/evidence");
    return catalogApi<ExperienceAdminRow[]>(`/admin/experience/${encodeURIComponent(section)}`);
  },
  scanDeadEnds: () => catalogApi<{ passed: boolean; routes_scanned: number; critical_count: number }>("/admin/experience/dead-ends/scan", { method: "POST" })
};
