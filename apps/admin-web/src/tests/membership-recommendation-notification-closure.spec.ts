import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function source(path: string) {
  return readFileSync(resolve(srcDirectory, path), "utf8");
}

describe("membership plan-to-sellable closure", () => {
  it("walks a plan version from draft to live", () => {
    const api = source("features/memberships/api.ts");
    const page = source("pages/MembershipManagementPage.vue");

    expect(api).toContain("/plans/${encodeURIComponent(planId)}/versions");
    expect(api).toContain("/membership-plan-versions/${encodeURIComponent(versionId)}/${action}");
    for (const action of ["submit-review", "approve", "activate", "retire"]) {
      expect(page).toContain(`'${action}'`);
    }
  });

  it("keeps a version it just created addressable", () => {
    const page = source("pages/MembershipManagementPage.vue");

    // There is no endpoint that lists plan versions, so a new draft would be
    // unreachable the moment the response scrolled away.
    expect(page).toContain("recentVersions");
    expect(page).toContain("后端没有提供版本列表端点");
  });

  it("supports the three-step manual grant and quota adjustment", () => {
    const api = source("features/memberships/api.ts");
    const page = source("pages/MembershipManagementPage.vue");

    expect(api).toContain("/manual-grants");
    expect(api).toContain("/manual-grants/${encodeURIComponent(grantId)}/${action}");
    expect(api).toContain("/quota-buckets/${encodeURIComponent(bucketId)}/adjustments");
    expect(page).toContain("需另一位具备审批权限的管理员批准");
    expect(page).toContain('auth.hasPermission("memberships.quotas.adjust")');
  });

  it("drops the tab whose backend resource does not exist", () => {
    // memberships ADMIN_RESOURCE_PERMISSIONS has no `incidents` key, so the
    // section answered 404 every time it was opened.
    expect(source("pages/MembershipManagementPage.vue")).not.toContain("memberships.incidents.read");
    expect(source("navigation/admin-nav.ts")).not.toContain("memberships.incidents.read");
  });

  it("stops rendering plans data under the SKU mapping tab", () => {
    const page = source("pages/MembershipManagementPage.vue");

    expect(page).toContain('section.value === "sku-mappings") rows.value = []');
    expect(page).toContain("createSkuMapping");
  });
});

describe("recommendation origination closure", () => {
  it("can create a strategy draft and an experiment", () => {
    const api = source("features/recommendations/api.ts");
    const page = source("pages/RecommendationManagementPage.vue");

    expect(api).toContain("createStrategy");
    expect(api).toContain("createExperiment");
    expect(page).toContain('auth.hasPermission("recommendations.strategies.create")');
    expect(page).toContain('auth.hasPermission("recommendations.experiments.create")');
  });

  it("clones an existing strategy rather than asking for eight blank policies", () => {
    const page = source("pages/RecommendationManagementPage.vue");

    expect(page).toContain("POLICY_FIELDS");
    expect(page).toContain("recommendationApi.getStrategy(sourceId)");
    expect(page).toContain("基于此新建版本");
  });

  it("refuses an experiment with no hypothesis", () => {
    expect(source("pages/RecommendationManagementPage.vue")).toContain(
      "form.hypothesis.trim().length < 10",
    );
  });
});

describe("notification navigation", () => {
  it("maps every section key onto a pane that exists", () => {
    const page = source("pages/NotificationManagementPage.vue");

    expect(page).toContain("SECTION_TO_TAB");
    for (const key of ["template-releases", "event-subscriptions", "dead-letters", "provider-events"]) {
      expect(page).toContain(key);
    }
  });

  it("drops the section the backend never exposed", () => {
    // Only a public token-based unsubscribe exists; there is no admin listing.
    expect(source("navigation/admin-nav.ts")).not.toContain("notifications.preferences.read");
  });
});
