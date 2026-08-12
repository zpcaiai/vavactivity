import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function source(path: string) {
  return readFileSync(resolve(srcDirectory, path), "utf8");
}

describe("data governance closure", () => {
  it("drives the backfill lifecycle from the console", () => {
    const api = source("features/data-governance/api.ts");
    const page = source("pages/DataGovernancePage.vue");

    expect(api).toContain("/backfills/${encodeURIComponent(runId)}/action");
    for (const action of ["approve", "start", "pause", "resume", "complete", "fail", "cancel"]) {
      expect(page).toContain(`action: "${action}"`);
    }
    // The offered transitions follow the run's own status, so the console never
    // sends a transition the backend would reject.
    expect(page).toContain("BACKFILL_ACTIONS[String(row.status ?? \"\")]");
  });

  it("can plan an erasure and certify it — the compliance path", () => {
    const api = source("features/data-governance/api.ts");
    const page = source("pages/DataGovernancePage.vue");

    expect(api).toContain("/erasures/plans");
    expect(api).toContain("/erasures/plans/${encodeURIComponent(planId)}/certificate");
    expect(page).toContain("lineage_release_version");
    expect(page).toContain('auth.hasPermission("data.erasures.plan")');
    expect(page).toContain('auth.hasPermission("data.erasures.certify")');
  });

  it("says plainly that per-task erasure receipts have no list endpoint yet", () => {
    // Better an honest gap than a control that cannot discover its own task ids.
    expect(source("pages/DataGovernancePage.vue")).toContain("后端尚未提供任务列表端点");
  });

  it("links a repair to the difference that justified it", () => {
    const page = source("pages/DataGovernancePage.vue");

    expect(page).toContain("reconciliation_difference_id");
    expect(page).toContain('section.value === "differences" ? String(row?.id ?? "") : ""');
  });

  it("rebuilds projections and registers external identifiers", () => {
    const api = source("features/data-governance/api.ts");

    expect(api).toContain("/projections/rebuild");
    expect(api).toContain("/external-identifiers");
  });

  it("validates operator-supplied JSON instead of posting a broken body", () => {
    const page = source("pages/DataGovernancePage.vue");

    expect(page).toContain("function parseJson");
    expect(page).toContain("必须是合法的 JSON 对象");
  });

  it("keeps pipeline-only endpoints out of the console", () => {
    const api = source("features/data-governance/api.ts");

    // These take machine-computed evidence (payload hashes, comparison sets,
    // evaluated/failed counts). A hand-typed form would fabricate compliance
    // evidence, so the client deliberately exposes no helper for them.
    for (const path of [
      "/events/outbox",
      "/events/inbox",
      "/reconciliations/run",
      "/quality/evaluate",
      "/certifications/evaluate",
    ]) {
      expect(api).not.toContain(`catalogApi<DataGovernanceRow>(\`\${BASE}${path}\``);
    }
  });

  it("closes the integrity certification with a typed reason", () => {
    const api = source("features/data-governance/api.ts");
    const page = source("pages/DataGovernancePage.vue");

    expect(api).toContain("/certifications/${encodeURIComponent(certificationId)}/decide");
    expect(page).toContain("reason.trim().length < 10");
  });
});
