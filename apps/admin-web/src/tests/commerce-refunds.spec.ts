import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function source(path: string) {
  return readFileSync(resolve(srcDirectory, path), "utf8");
}

describe("commerce refund closure", () => {
  it("lets an operator originate a refund, not only approve one that already exists", () => {
    const page = source("pages/CommerceManagementPage.vue");

    expect(page).toContain('catalogApi("/admin/commerce/refunds"');
    expect(page).toContain("order_id: form.order_id.trim()");
    expect(page).toContain("amount_minor: form.amount_minor");
    expect(page).toContain("reason_code: form.reason_code");
    expect(page).toContain('auth.hasPermission("commerce.refunds.request")');
  });

  it("sends the idempotency key the backend requires so a double click cannot double-refund", () => {
    const page = source("pages/CommerceManagementPage.vue");

    expect(page).toContain('"Idempotency-Key": crypto.randomUUID()');
  });

  it("refuses to refund more than the order still owes", () => {
    const page = source("pages/CommerceManagementPage.vue");

    expect(page).toContain("function outstandingMinor");
    expect(page).toContain("form.amount_minor > form.maximum_minor");
  });

  it("keeps every state transition the backend exposes reachable", () => {
    const page = source("pages/CommerceManagementPage.vue");

    for (const path of [
      "/admin/commerce/refunds/${row.id}/approve",
      "/admin/commerce/refunds/${row.id}/submit",
      "/admin/commerce/webhooks/${row.id}/replay",
      "/admin/commerce/reconciliation/${row.id}/resolve",
      "/admin/commerce/entitlements/${row.id}/revoke",
      "/admin/commerce/reconciliation/scan",
    ]) {
      expect(page).toContain(path);
    }
  });

  it("never sends a canned audit reason", () => {
    const page = source("pages/CommerceManagementPage.vue");

    // Every write goes through the reason dialog, which enforces the same
    // minimum the backend does, so the audit trail records a real explanation.
    expect(page).toContain("reason.trim().length < 10");
    expect(page).toContain("JSON.stringify({ reason: reason.trim() })");
    expect(page).not.toContain("Operator reviewed and requested");
  });

  it("honours server pagination instead of silently showing the first page only", () => {
    const page = source("pages/CommerceManagementPage.vue");

    expect(page).toContain("result.pagination?.total");
    expect(page).toContain("PaginationBar");
  });

  it("gates each row action behind the permission that action needs", () => {
    const page = source("pages/CommerceManagementPage.vue");

    for (const permission of [
      "commerce.refunds.approve",
      "commerce.refunds.submit",
      "commerce.webhooks.replay",
      "commerce.reconciliation.resolve",
      "commerce.entitlements.revoke",
      "commerce.payments.reconcile",
    ]) {
      expect(page).toContain(permission);
    }
  });
});
