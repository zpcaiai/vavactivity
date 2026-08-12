import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function source(path: string) {
  return readFileSync(resolve(srcDirectory, path), "utf8");
}

describe("process governance closure", () => {
  it("lets an operator resolve the intervention task a stuck scan produced", () => {
    const api = source("features/process-governance/api.ts");
    const page = source("pages/ProcessGovernancePage.vue");

    expect(api).toContain("/admin/processes/interventions/${encodeURIComponent(taskId)}/resolve");
    expect(page).toContain("processApi.resolveIntervention");
    expect(page).toContain('auth.hasPermission("process.interventions.execute")');
  });

  it("offers only the commands the task itself registered", () => {
    const page = source("pages/ProcessGovernancePage.vue");

    // The backend answers 403 PROCESS_UNREGISTERED_REPAIR_REJECTED for anything
    // outside allowed_resolution_commands, so the picker is bounded by the row.
    expect(page).toContain("allowedCommands");
    expect(page).toContain("task?.allowed_resolution_commands");
  });

  it("opens the instance the backend has always been able to describe", () => {
    const api = source("features/process-governance/api.ts");
    const page = source("pages/ProcessGovernancePage.vue");

    expect(api).toContain("/admin/processes/instances/${encodeURIComponent(instanceId)}");
    expect(page).toContain("instanceModal.detail.steps");
    expect(page).toContain("instanceModal.detail.compensations");
  });

  it("cancels under the optimistic lock instead of blind-writing", () => {
    const api = source("features/process-governance/api.ts");
    const page = source("pages/ProcessGovernancePage.vue");

    expect(api).toContain("/cancel");
    expect(api).toContain("cancellation_key: operationKey(\"cancel\")");
    expect(page).toContain("expected_lock_version: Number(instance.lock_version ?? 0)");
  });

  it("can raise a compensation against a specific step execution", () => {
    const api = source("features/process-governance/api.ts");

    expect(api).toContain("/compensations");
    expect(api).toContain("step_execution_id: stepExecutionId");
    expect(api).toContain("idempotency_key: operationKey(\"compensate\")");
  });

  it("closes the certification loop with a typed reason", () => {
    const api = source("features/process-governance/api.ts");
    const page = source("pages/ProcessGovernancePage.vue");

    expect(api).toContain("/decide");
    expect(page).toContain("reason.trim().length < 10");
    expect(page).toContain('auth.hasPermission("process.certifications.certify")');
  });

  it("gives the shared admin table a row action column", () => {
    // Governance pages could not put a control on a row at all before this.
    expect(source("../../../packages/ui-admin/src/tables/AdminDataTable.vue")).toContain(
      "$slots.actions",
    );
  });
});
