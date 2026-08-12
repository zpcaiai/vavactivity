import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

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
      expect(source).toContain(`'${action}'`);
    }
  });

  it("gates each step behind the permission that step needs", () => {
    const source = page();

    for (const permission of [
      "notifications.templates.update",
      "notifications.templates.approve",
      "notifications.templates.activate",
      "notifications.templates.rollback",
      "notifications.templates.test_send",
    ]) {
      expect(source).toContain(permission);
    }
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
