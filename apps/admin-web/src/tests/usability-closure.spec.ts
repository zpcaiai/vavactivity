import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  ASSERTED_DIMENSIONS,
  DERIVED_DIMENSIONS,
  certificationStatus,
  deriveDimension,
  parseCsv
} from "@/features/usability/api";
import { usabilitySectionPermissions } from "@/navigation/admin-nav";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(srcDirectory, "../../..");

function source(path: string) {
  return readFileSync(resolve(srcDirectory, path), "utf8");
}

function locale(name: string) {
  return JSON.parse(source(`i18n/locales/${name}.json`)) as {
    menu: Record<string, string>;
    section: Record<string, string>;
  };
}

describe("usability section wiring", () => {
  it("mirrors the section keys the backend router actually serves", () => {
    const routerPath = resolve(
      repoRoot,
      "services/api/src/vav/modules/usability/admin_router.py"
    );
    // The console builds GET /admin/usability/{section} straight from this map;
    // a key the backend does not know resolves to the dashboard permission and
    // then 404s, which is how the other modules ended up with phantom tabs.
    expect(existsSync(routerPath)).toBe(true);
    const backend = readFileSync(routerPath, "utf8");
    const block = backend.slice(backend.indexOf("PERMISSIONS = {"));
    const backendSections = [...block.matchAll(/^\s{4}"([^"]+)":/gmu)].map((match) => match[1]);

    expect(backendSections.length).toBeGreaterThan(0);
    for (const key of backendSections) {
      expect(Object.keys(usabilitySectionPermissions)).toContain(key);
    }
    // `dashboard` is served by its own endpoint rather than the section route.
    for (const key of Object.keys(usabilitySectionPermissions)) {
      if (key === "dashboard") continue;
      expect(backendSections).toContain(key);
    }
  });

  it("labels every section in all three locales", () => {
    const locales = ["zh-CN", "zh-TW", "en"].map(locale);
    for (const messages of locales) {
      expect(messages.menu.usability).toBeTruthy();
      for (const key of Object.keys(usabilitySectionPermissions)) {
        expect(messages.section[key]).toBeTruthy();
      }
    }
  });

  it("registers the module in navigation and the router", () => {
    const nav = source("navigation/admin-nav.ts");
    const router = source("router/index.ts");

    expect(nav).toContain('base: "/admin/usability"');
    expect(nav).toContain("sectionsOf(usabilitySectionPermissions)");
    expect(router).toContain("usabilitySection: section");
    expect(router).toContain("UsabilityManagementPage");
  });
});

describe("certification evidence", () => {
  it("splits dimensions into derivable and asserted", () => {
    // uat / compatibility / localization runs carry release_version and
    // environment, so they are computed. Drafts, notification QA cases and
    // import jobs carry neither and cannot be attributed to a release.
    expect(DERIVED_DIMENSIONS).toEqual(["uat", "compatibility", "localization"]);
    expect(ASSERTED_DIMENSIONS).toEqual(["draft", "notification", "import_export"]);
  });

  it("mirrors the backend's fail-closed aggregation", () => {
    const passing = {
      uat: "passed",
      compatibility: "passed",
      localization: "passed",
      draft: "passed",
      notification: "passed",
      import_export: "passed"
    };

    expect(certificationStatus(passing, 0)).toBe("certified");
    // An unresolved critical finding rejects outright, however green the rest.
    expect(certificationStatus(passing, 1)).toBe("rejected");
    expect(certificationStatus({ ...passing, uat: "failed" }, 0)).toBe("rejected");
    expect(certificationStatus({ ...passing, uat: "needs_retest" }, 0)).toBe("rejected");
    expect(certificationStatus({ ...passing, uat: "not_run" }, 0)).toBe("eligible");
    // A missing dimension is rejected rather than silently treated as not_run.
    const incomplete: Record<string, string> = { ...passing };
    delete incomplete.import_export;
    expect(certificationStatus(incomplete, 0)).toBe("rejected");
    expect(certificationStatus({ ...passing, uat: "bogus" }, 0)).toBe("rejected");
  });

  it("never lets an unfinished run count as a pass", () => {
    const rows = [
      { release_version: "1.2.0", environment: "staging", status: "passed" },
      { release_version: "1.2.0", environment: "staging", status: "running" },
      { release_version: "1.2.0", environment: "production", status: "failed" }
    ];

    expect(deriveDimension(rows, "1.2.0", "staging")).toEqual({
      status: "not_run",
      matched: 2,
      failed: 0,
      blocked: 0,
      pending: 1
    });
    expect(deriveDimension(rows, "1.2.0", "production").status).toBe("failed");
    expect(deriveDimension(rows, "9.9.9", "staging").status).toBe("not_run");
    expect(deriveDimension([{ release_version: "1.2.0", environment: "ci", status: "passed" }], "1.2.0", "ci").status).toBe("passed");
  });

  it("requires evidence before an asserted dimension may pass", () => {
    const page = source("pages/UsabilityManagementPage.vue");

    expect(page).toContain("assertedPassWithoutEvidence");
    expect(page).toContain('asserted: { draft: "not_run", notification: "not_run", import_export: "not_run" }');
    // The verdict is shown before submitting because the endpoint upserts.
    expect(page).toContain("certPreview");
  });
});

describe("uat execution", () => {
  it("offers only the locales and devices the scenario declares", () => {
    const page = source("pages/UsabilityManagementPage.vue");

    expect(page).toContain("scenarioLocales");
    expect(page).toContain("scenarioDevices");
    expect(page).toContain("USABILITY_UAT_MATRIX_MISMATCH");
  });

  it("seeds one result row per scenario step", () => {
    const page = source("pages/UsabilityManagementPage.vue");

    expect(page).toContain("definition.map(() => ({ status: \"not_run\"");
    expect(page).toContain("后端要求逐步结果数量与场景定义完全一致");
  });
});

describe("imports", () => {
  it("parses quoted csv fields without splitting them", () => {
    const rows = parseCsv('email,note\r\n"a@example.test","hello, world"\r\n"b@example.test","line\nbreak"\r\n');

    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual({ email: "a@example.test", note: "hello, world" });
    expect(rows[1].note).toBe("line\nbreak");
  });

  it("returns nothing when the file has only a header", () => {
    expect(parseCsv("email,note\n")).toEqual([]);
  });

  it("says plainly that preview does not import", () => {
    const page = source("pages/UsabilityManagementPage.vue");

    // There is no commit endpoint: /imports/preview is the only write the
    // backend exposes, so the console must not imply the data landed.
    expect(page).toContain("不会把数据写进业务表");
    expect(page).toContain("dry_run: true");
  });
});

describe("drafts stay out of the console", () => {
  it("does not build an operator form for save_draft", () => {
    const api = source("features/usability/api.ts");
    const page = source("pages/UsabilityManagementPage.vue");

    // POST /admin/usability/drafts is the client-side autosave path: it writes
    // an encrypted payload under the calling user's own id. An operator filling
    // that in by hand would be manufacturing another person's draft.
    expect(api).not.toContain("saveDraft");
    expect(page).not.toContain("client_version");
    expect(page).toContain("不是管理端可以代填的对象");
  });
});
