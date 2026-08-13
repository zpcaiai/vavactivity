import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  getTemplateReleaseActions,
  type TemplateReleaseStatus,
} from "../pages/NotificationManagementPage.vue";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function page() {
  return readFileSync(resolve(srcDirectory, "pages/NotificationManagementPage.vue"), "utf8");
}

describe("notification template publishing closure", () => {
  it("can create a template definition", () => {
    const source = page();

    expect(source).toContain('catalogApi("/admin/notifications/templates"');
    expect(source).toContain("variable_schema: schema");
    expect(source).toContain('auth.hasPermission("notifications.templates.create")');
  });

  it("can cut a release and walk it to live", () => {
    const source = page();

    expect(source).toContain("/admin/notifications/templates/${templateId}/releases");
    expect(source).toContain("/admin/notifications/template-releases/${item.id}/${action}");
    for (const action of ["submit-review", "approve", "activate", "revoke", "rollback"]) {
      expect(source).toContain(`action: "${action}"`);
    }
  });

  it("matches every release status to the backend action matrix", () => {
    const statuses: readonly TemplateReleaseStatus[] = [
      "draft",
      "in_review",
      "approved",
      "active",
      "superseded",
      "revoked",
    ];
    const expected: Record<TemplateReleaseStatus, string[]> = {
      draft: ["submit-review", "preview", "test-send"],
      in_review: ["approve", "preview", "test-send"],
      approved: ["activate", "rollback", "preview", "test-send"],
      active: ["revoke", "preview", "test-send"],
      superseded: ["rollback", "revoke", "preview", "test-send"],
      revoked: ["preview", "test-send"],
    };

    for (const status of statuses) {
      expect(
        getTemplateReleaseActions(status, () => true).map(({ action }) => action),
      ).toEqual(expected[status]);
    }
  });

  it("gates lifecycle actions and test-send behind their backend permissions", () => {
    const actions = (status: TemplateReleaseStatus, permissions: string[]) =>
      getTemplateReleaseActions(status, (permission) => permissions.includes(permission))
        .map(({ action }) => action);

    for (const status of [
      "draft",
      "in_review",
      "approved",
      "active",
      "superseded",
      "revoked",
    ] as const) {
      expect(actions(status, [])).toEqual(["preview"]);
      expect(actions(status, ["notifications.templates.test_send"])).toContain("test-send");
    }

    expect(actions("draft", ["notifications.templates.update"]))
      .toEqual(["submit-review", "preview"]);
    expect(actions("in_review", ["notifications.templates.approve"]))
      .toEqual(["approve", "preview"]);
    expect(actions("approved", ["notifications.templates.activate"]))
      .toEqual(["activate", "preview"]);
    expect(actions("approved", ["notifications.templates.rollback"]))
      .toEqual(["rollback", "preview"]);
    expect(actions("active", ["notifications.templates.rollback"]))
      .toEqual(["revoke", "preview"]);
    expect(actions("superseded", ["notifications.templates.rollback"]))
      .toEqual(["rollback", "revoke", "preview"]);
  });

  it("renders buttons from the tested policy instead of duplicating status checks", () => {
    const source = page();

    expect(source).toContain("v-for=\"actionDefinition in templateReleaseActions(scope.row.status)\"");
    expect(source).toContain("runTemplateReleaseAction(scope.row, actionDefinition.action)");
  });

  it("requires the plain-text body every channel falls back to", () => {
    expect(page()).toContain("form.body_text_template.trim()");
  });

  it("separates a dry preview from a real test send", () => {
    const source = page();

    expect(source).toContain("/admin/notifications/template-releases/${form.release_id}/preview");
    expect(source).toContain("/admin/notifications/template-releases/${form.release_id}/test-send");
    // The wording has to make the difference obvious: one renders, one delivers.
    expect(source).toContain("不会发给任何人");
    expect(source).toContain("会真实投递到指定收件人");
  });

  it("makes a rollback carry a typed reason", () => {
    const source = page();

    expect(source).toContain("requireTemplateReason");
    expect(source).toContain('action === "rollback" ? JSON.stringify({ reason: reason.value.trim() }) : undefined');
  });
});
