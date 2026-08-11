import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function source(path: string) {
  return readFileSync(resolve(srcDirectory, path), "utf8");
}

describe("admin management closure", () => {
  it("routes user management to the dedicated lifecycle page", () => {
    const router = source("router/index.ts");

    expect(router).toContain(
      'const UserManagementPage = () => import("@/pages/UserManagementPage.vue")',
    );
    expect(router).toMatch(/path: "users",[\s\S]*component: UserManagementPage/u);
  });

  it("supports the complete user lifecycle and history", () => {
    const page = source("pages/UserManagementPage.vue");

    expect(page).toContain('method: "PATCH"');
    expect(page).toContain('"suspend" | "restore" | "deactivate" | "sessions/revoke"');
    expect(page).toContain("/history?page_size=100");
    expect(page).toContain("注销用户账户");
  });

  it("supports schedules, rescheduling, cancellation, and follow-ups", () => {
    const page = source("pages/CounselingManagementPage.vue");

    expect(page).toContain("/admin/counseling/availability-rules");
    expect(page).toContain("/propose-time");
    expect(page).toContain("transition(scope.row, 'cancelled')");
    expect(page).toContain("/admin/counseling/follow-ups/");
  });

  it("uses dedicated settings and administrator workbenches", () => {
    const router = source("router/index.ts");
    const settings = source("pages/SiteSettingsPage.vue");
    const admins = source("pages/AdminManagementPage.vue");

    expect(router).toContain("component: SiteSettingsPage");
    expect(router).toContain("component: AdminManagementPage");
    expect(settings).toContain("/history");
    expect(settings).toContain("/rollback");
    expect(admins).toContain("/admin/admins/invitations");
    expect(admins).toContain("/roles/");
    expect(admins).toContain("停用管理员");
  });

  it("renames pages to content center and hides the duplicate platform navigation", () => {
    const layout = source("layouts/AdminLayout.vue");
    const locale = source("i18n/locales/zh-CN.json");

    expect(locale).toContain('"pages": "内容中心"');
    expect(layout).not.toContain('path: "/admin/platform/dashboard"');
  });
});
