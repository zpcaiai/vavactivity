import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function source(path: string) {
  return readFileSync(resolve(srcDirectory, path), "utf8");
}

describe("contact submission closure", () => {
  it("routes the module to its dedicated workbench instead of the generic read-only table", () => {
    const router = source("router/index.ts");

    expect(router).toContain(
      'const ContactSubmissionPage = () => import("@/pages/ContactSubmissionPage.vue")',
    );
    expect(router).toMatch(
      /path: "content\/contact-submissions",[\s\S]*?component: ContactSubmissionPage/u,
    );
    // The legacy top-level path must keep working for bookmarked links.
    expect(router).toMatch(
      /path: "contact-submissions",\s*redirect: "\/admin\/content\/contact-submissions"/u,
    );
  });

  it("exposes the module in navigation so operators can find it", () => {
    const navigation = source("navigation/admin-nav.ts");

    expect(navigation).toContain('section("contact-submissions", "contact.submissions.read")');
    for (const locale of ["zh-CN", "zh-TW", "en"]) {
      expect(source(`i18n/locales/${locale}.json`)).toContain('"contact-submissions"');
    }
  });

  it("closes the loop: assign, transition, resolve and export are all reachable", () => {
    const page = source("pages/ContactSubmissionPage.vue");

    expect(page).toContain("/admin/contact-submissions/${selected.value.id}/status");
    expect(page).toContain('method: "PATCH"');
    expect(page).toContain("/admin/contact-submissions/${selected.value.id}/assign");
    expect(page).toContain("/admin/contact-submissions/${selected.value.id}/resolve");
    expect(page).toContain("/admin/contact-submissions/export");
  });

  it("covers every status the backend accepts", () => {
    const page = source("pages/ContactSubmissionPage.vue");

    for (const status of [
      "new",
      "in_progress",
      "waiting_external",
      "resolved",
      "spam",
      "archived",
    ]) {
      expect(page).toContain(`value: "${status}"`);
    }
  });

  it("never writes an audit reason the operator did not type", () => {
    const page = source("pages/ContactSubmissionPage.vue");

    // The backend enforces min_length=10 on reason/resolution; the operator has
    // to supply it, so a canned string can never end up in the audit trail.
    expect(page).toContain("value.trim().length >= 10");
    expect(page).toContain("statusForm.value.reason.trim()");
    expect(page).toContain("assignForm.value.reason.trim()");
    expect(page).toContain("resolveForm.value.resolution.trim()");
  });

  it("gates every write behind the permission the backend requires", () => {
    const page = source("pages/ContactSubmissionPage.vue");

    expect(page).toContain('auth.hasPermission("contact.submissions.assign")');
    expect(page).toContain('auth.hasPermission("contact.submissions.resolve")');
    expect(page).toContain('auth.hasPermission("contact.submissions.export")');
  });
});
