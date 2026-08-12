import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function source(path: string) {
  return readFileSync(resolve(srcDirectory, path), "utf8");
}

describe("privacy operations closure", () => {
  it("verifies identity before deciding a data-rights request", () => {
    const page = source("pages/PrivacyManagementPage.vue");

    expect(page).toContain("/admin/privacy/requests/${row.id}/${action}");
    expect(page).toContain('"verify-identity"');
    expect(page).toContain('auth.hasPermission("privacy.requests.verify_identity")');
  });

  it("can actually produce the encrypted export an approval promises", () => {
    const page = source("pages/PrivacyManagementPage.vue");

    expect(page).toContain("/admin/privacy/exports/${row.id}/process");
    expect(page).toContain('auth.hasPermission("privacy.exports.generate")');
  });

  it("can create and release a legal hold", () => {
    const page = source("pages/PrivacyManagementPage.vue");

    expect(page).toContain('catalogApi("/admin/privacy/legal-holds"');
    expect(page).toContain("/admin/privacy/legal-holds/${row.id}/release");
    // A hold blocks a user's erasure right, so it needs an authoriser, a bounded
    // scope and an end date — never an open-ended block.
    expect(page).toContain("authorized_by");
    expect(page).toContain("module_codes: modules");
    expect(page).toContain("ends_at: form.ends_at");
  });

  it("can raise a break-glass request, not only approve one", () => {
    const page = source("pages/PrivacyManagementPage.vue");

    expect(page).toContain('catalogApi("/admin/privacy/break-glass"');
    expect(page).toContain("data_scope: scope");
  });

  it("stopped shipping a canned justification and a canned user message", () => {
    const page = source("pages/PrivacyManagementPage.vue");

    expect(page).not.toContain("Batch 12 governed privacy operation.");
    expect(page).not.toContain("Your request was approved for governed processing.");
    expect(page).not.toContain("Correction approved; historical facts remain preserved.");
    expect(page).toContain("user_visible_message: userMessage.value.trim()");
    expect(page).toContain("function requireReason");
  });

  it("states plainly which two actions the backend records without a reason", () => {
    // execute-erasure and use-break-glass take no request body at all, so the
    // console says where their traceability actually comes from.
    expect(source("pages/PrivacyManagementPage.vue")).toContain("不接收理由字段");
  });
});

describe("ai referral closure", () => {
  it("lets an acknowledged referral be assigned and closed", () => {
    const page = source("pages/AiManagementPage.vue");

    expect(page).toContain('{ action: "assign", assigned_to: form.assigned_to.trim() }');
    expect(page).toContain('{ action: "resolve", resolution: form.resolution.trim() }');
    expect(page).toContain('auth.hasPermission(\'ai.referrals.resolve\')');
  });

  it("requires a real resolution before closing a safety referral", () => {
    const page = source("pages/AiManagementPage.vue");

    expect(page).toContain("form.resolution.trim().length < 10");
  });
});
