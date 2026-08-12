import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function source(path: string) {
  return readFileSync(resolve(srcDirectory, path), "utf8");
}

describe("course monetisation closure", () => {
  it("can attach a course to a sellable SKU from the console", () => {
    const page = source("pages/CourseManagementPage.vue");

    expect(page).toContain("/admin/courses/${selectedCourseId.value}/catalog-mappings");
    expect(page).toContain("catalog_sku_id: mappingForm.catalog_sku_id");
    expect(page).toContain('access_start_policy: "entitlement_activation"');
    expect(page).toContain('course_version_policy: "pin_at_enrollment"');
  });

  it("can list and detach existing mappings", () => {
    const page = source("pages/CourseManagementPage.vue");

    expect(page).toContain("loadCatalogMappings");
    expect(page).toContain(
      "/admin/courses/${selectedCourseId.value}/catalog-mappings/${mapping.id}",
    );
    expect(page).toContain('method: "DELETE"');
  });

  it("only offers SKUs the backend will actually accept", () => {
    const page = source("pages/CourseManagementPage.vue");

    // The backend rejects anything that is not a digital-access course or
    // course-bundle SKU, so the picker filters to the same set.
    expect(page).toContain('["course", "course_bundle"].includes(String(product.product_type))');
    expect(page).toContain('String(product.fulfillment_type) === "digital_access"');
  });

  it("gates the tab behind the catalog permission", () => {
    const page = source("pages/CourseManagementPage.vue");

    expect(page).toContain('auth.hasPermission("courses.catalog.manage")');
    expect(page).toContain('["catalog.products.read", "catalog.skus.read"]');
  });
});
