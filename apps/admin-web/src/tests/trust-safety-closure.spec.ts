import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { CASE_TRANSITIONS, HIGH_IMPACT_RESTRICTIONS } from "@/features/trust-safety/api";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function page() {
  return readFileSync(resolve(srcDirectory, "pages/TrustSafetyManagementPage.vue"), "utf8");
}

describe("trust & safety case state machine", () => {
  it("mirrors the backend's CASE_TRANSITIONS exactly", () => {
    // Copied from services/api/.../trust_safety/domain.py. If the backend edges
    // change, this test is where the console finds out.
    expect(CASE_TRANSITIONS).toEqual({
      open: ["triaged", "assigned", "closed"],
      triaged: ["assigned", "investigating", "closed"],
      assigned: ["investigating", "pending_action", "resolved"],
      investigating: ["pending_action", "resolved"],
      pending_action: ["investigating", "resolved"],
      resolved: ["closed", "reopened"],
      closed: ["reopened"],
      reopened: ["assigned", "investigating"],
    });
  });

  it("offers only transitions legal from the row's own status", () => {
    const source = page();

    expect(source).toContain("function caseTransitions");
    expect(source).toContain('CASE_TRANSITIONS[String(row.status ?? "")]');
    // The old console hard-coded two edges and sent whatever was clicked.
    expect(source).not.toContain("row.status === \"open\" ? \"triaged\" : \"investigating\"");
  });
});

describe("trust & safety decisions carry real content", () => {
  it("no longer ships a canned moderation decision", () => {
    const source = page();

    expect(source).not.toContain("内容正在人工复核。");
    expect(source).not.toContain('reason_code: "human_review_required"');
    expect(source).toContain("form.internal_note.trim().length < 10");
  });

  it("refuses an unexplainable removal", () => {
    const source = page();

    // Removing or limiting content without a category tells the author they
    // were actioned but not under which rule.
    expect(source).toContain('["remove", "limit", "reject"].includes(form.decision)');
  });

  it("can decide an appeal, which was dead code before", () => {
    const source = page();

    expect(source).toContain("safetyAdminApi.decideAppeal");
    expect(source).toContain('auth.hasPermission("safety.appeals.decide")');
    for (const outcome of ["upheld", "modified", "overturned", "ineligible"]) {
      expect(source).toContain(`value: "${outcome}"`);
    }
  });
});

describe("account restriction lifecycle", () => {
  it("can create, approve and lift a restriction", () => {
    const source = page();

    expect(source).toContain("safetyAdminApi.createRestriction");
    expect(source).toContain("safetyAdminApi.approveRestriction");
    expect(source).toContain("safetyAdminApi.liftRestriction");
    expect(source).toContain('auth.hasPermission("safety.restrictions.create")');
    expect(source).toContain('auth.hasPermission("safety.restrictions.high_impact.approve")');
    expect(source).toContain('auth.hasPermission("safety.restrictions.lift")');
  });

  it("warns before creating a high-impact restriction", () => {
    expect(HIGH_IMPACT_RESTRICTIONS).toEqual([
      "account_permanently_disabled",
      "account_temporarily_suspended",
      "reverification_required",
    ]);
    expect(page()).toContain("HIGH_IMPACT_RESTRICTIONS.includes(form.restriction_type)");
  });

  it("requires a typed reason to lift", () => {
    expect(page()).toContain("form.reason.trim().length < 10");
  });
});
