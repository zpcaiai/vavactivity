import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function page() {
  return readFileSync(resolve(srcDirectory, "pages/KnowledgeManagementPage.vue"), "utf8");
}

describe("knowledge authorisation closure", () => {
  it("makes the authorisation decision reachable, not just visible", () => {
    const source = page();

    // "Authorisation precedes indexing" is the module's own rule; the decision
    // has to be executable from the console or the rule is unenforceable here.
    expect(source).toContain("/admin/knowledge/authorizations/${row.id}/${action}");
    expect(source).toContain('decideAuthorization(scope.row, \'approve\')');
    expect(source).toContain('decideAuthorization(scope.row, \'reject\')');
    expect(source).toContain('decideAuthorization(scope.row, \'revoke\')');
  });

  it("shows what a revocation breaks before it is executed", () => {
    const source = page();

    expect(source).toContain("/admin/knowledge/authorizations/${row.id}/impact");
    expect(source).toContain("requires_index_repair");
  });

  it("can originate an authorisation for a document and for a whole source", () => {
    const source = page();

    expect(source).toContain("/admin/knowledge/documents/${form.document_id}/authorizations");
    expect(source).toContain("/admin/knowledge/sources/${form.source_id}/authorizations");
    // The backend stores the evidence encrypted; it must come from the operator.
    expect(source).toContain("evidence_reference");
    expect(source).toContain("form.evidence_reference.trim().length < 2");
  });

  it("closes the document version loop: review then publish", () => {
    const source = page();

    expect(source).toContain("/admin/knowledge/document-versions/${version.id}/review");
    expect(source).toContain("/admin/knowledge/document-versions/${form.version_id}/publish");
    expect(source).toContain('reviewVersion(scope.row, \'approve\')');
    expect(source).toContain('reviewVersion(scope.row, \'reject\')');
  });

  it("lets a parsing finding be dispositioned instead of only listed", () => {
    const source = page();

    expect(source).toContain("/admin/knowledge/document-versions/${version.id}/findings");
    expect(source).toContain("/admin/knowledge/findings/${finding.id}/review");
    for (const decision of ["resolved", "accepted_risk", "rejected"]) {
      expect(source).toContain(`value: "${decision}"`);
    }
  });

  it("can create the space and source that everything else hangs off", () => {
    const source = page();

    expect(source).toContain('catalogApi("/admin/knowledge/spaces"');
    expect(source).toContain("/admin/knowledge/spaces/${form.space_id}/sources");
  });

  it("stopped sending a canned reason when switching the live index", () => {
    const source = page();

    expect(source).not.toContain("管理端${action === \"activate\" ? \"激活\" : \"回滚\"}审批");
    expect(source).toContain("reason.trim().length < 10");
  });

  it("gates each governed action behind its backend permission", () => {
    const source = page();

    for (const permission of [
      "knowledge.spaces.manage",
      "knowledge.sources.manage",
      "knowledge.authorizations.approve",
      "knowledge.authorizations.manage",
      "knowledge.documents.review",
      "knowledge.documents.publish",
      "knowledge.indexes.manage",
    ]) {
      expect(source).toContain(permission);
    }
  });
});
