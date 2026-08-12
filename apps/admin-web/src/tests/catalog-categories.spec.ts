import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function source(path: string) {
  return readFileSync(resolve(srcDirectory, path), "utf8");
}

describe("catalog category closure", () => {
  it("gives categories a route and a navigation entry", () => {
    expect(source("router/index.ts")).toContain('catalogSection: "categories"');
    expect(source("navigation/admin-nav.ts")).toContain('section("categories", "catalog.products.read")');
    for (const locale of ["zh-CN", "zh-TW", "en"]) {
      expect(source(`i18n/locales/${locale}.json`)).toContain('"categories"');
    }
  });

  it("can list and create categories", () => {
    const page = source("pages/CatalogManagementPage.vue");

    expect(page).toContain('catalogApi<{ items: CatalogRow[] }>("/admin/catalog/categories")');
    expect(page).toContain("category_code: form.value.code.toLowerCase()");
    expect(page).toContain("parent_id: form.value.parentId || null");
    expect(page).toContain("localizations: [{");
  });

  it("stops asking the operator to paste a category UUID into the product form", () => {
    const page = source("pages/CatalogManagementPage.vue");

    expect(page).not.toContain("分类 UUID");
    expect(page).toContain('v-model="form.categoryId"');
    expect(page).toContain('v-for="category in categories"');
  });
});
