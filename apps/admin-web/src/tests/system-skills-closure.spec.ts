import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { SKILL_SECTIONS_WITHOUT_SOURCE } from "@/features/skills/api";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function source(path: string) {
  return readFileSync(resolve(srcDirectory, path), "utf8");
}

describe("system operations closure", () => {
  it("can approve and roll back a release", () => {
    const api = source("features/system/api.ts");
    const page = source("pages/SystemOperationsPage.vue");

    expect(api).toContain("/releases/${encodeURIComponent(id)}/approve");
    expect(api).toContain("/releases/${encodeURIComponent(id)}/rollback");
    expect(page).toContain('auth.hasPermission("system.releases.approve")');
    expect(page).toContain('auth.hasPermission("system.releases.rollback")');
  });

  it("can retry or cancel a job and replay a dead letter", () => {
    const api = source("features/system/api.ts");
    const page = source("pages/SystemOperationsPage.vue");

    expect(api).toContain("/jobs/${encodeURIComponent(id)}/${operation}");
    expect(api).toContain("/dead-letters/${encodeURIComponent(id)}/replay");
    expect(page).toContain('operateJob(row, \'retry\')');
    expect(page).toContain('operateJob(row, \'cancel\')');
    expect(page).toContain("replayDeadLetter(row)");
  });

  it("stopped sending a fixed maintenance reason code", () => {
    const page = source("pages/SystemOperationsPage.vue");

    expect(page).not.toContain('reason_code: "operator_confirmed_change"');
    expect(page).toContain("reason_code.trim().length < 3");
  });

  it("keeps pipeline receipts out of the console", () => {
    const api = source("features/system/api.ts");

    // Release records, deployment evidence, backups, restore drills and capacity
    // baselines carry image digests, contract checksums and artifact hashes.
    for (const helper of ["createRelease", "recordDeployment", "createBackup", "createRestoreDrill"]) {
      expect(api).not.toContain(`${helper}:`);
    }
    expect(source("pages/SystemOperationsPage.vue")).toContain("由执行方写入，控制台不提供手填入口");
  });
});

describe("skill console data sources", () => {
  it("names the sections the backend does not expose", () => {
    expect(SKILL_SECTIONS_WITHOUT_SOURCE).toEqual(["dependencies", "configurations", "audit"]);
    expect(source("pages/SkillManagementPage.vue")).toContain("已改为空视图而不是展示别处的数据");
  });

  it("reads publishers and incidents from their own endpoints", () => {
    const api = source("features/skills/api.ts");
    const page = source("pages/SkillManagementPage.vue");

    expect(api).toContain('catalogApi<SkillRow[]>("/admin/skills/publishers")');
    expect(api).toContain('catalogApi<SkillRow[]>("/admin/skills/incidents")');
    expect(page).toContain("skillsAdminApi.publishers()");
    expect(page).toContain("skillsAdminApi.incidents()");
    // Permissions belong to an installation, not to the public catalogue.
    expect(page).toContain('section.value === "permissions"');
  });

  it("exposes the supply-chain gates", () => {
    const api = source("features/skills/api.ts");
    const page = source("pages/SkillManagementPage.vue");

    expect(api).toContain("/security-review");
    expect(api).toContain("/quarantine");
    expect(api).toContain('"/admin/skills/signature-revocations"');
    // Quote-agnostic on purpose. These two gates are written inline in the
    // template, where the surrounding attribute is double-quoted and the inner
    // string therefore has to be single-quoted — so pinning double quotes here
    // asserted something the file could never satisfy, and the test failed on
    // correct code. What matters is that the permission gates the control.
    expect(page).toMatch(/auth\.hasPermission\(['"]skills\.security\.quarantine['"]\)/u);
    expect(page).toMatch(
      /auth\.hasPermission\(['"]skills\.security\.revoke_signature['"]\)/u
    );
  });

  it("stops shipping a canned reason code and empty findings", () => {
    const page = source("pages/SkillManagementPage.vue");

    expect(page).not.toContain('reason_code: "OPERATOR_CONFIRMED"');
    expect(page).toContain("^[A-Z][A-Z0-9_]{2,127}$");
    expect(page).toContain("要求修改必须至少写一条具体问题");
  });
});
