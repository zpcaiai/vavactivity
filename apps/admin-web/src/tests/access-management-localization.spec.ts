import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const pagePath = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../pages/AccessManagementPage.vue",
);
const source = readFileSync(pagePath, "utf8");

describe("access management table localization", () => {
  it("renders API keys and values through the shared Chinese display layer", () => {
    expect(source).toContain(':label="localizeAdminLabel(key)"');
    expect(source).toContain("localizeAdminValue(row[key], key)");
    expect(source).toContain(':min-width="adminColumnMinWidth(key)"');
    expect(source).not.toContain(':label="key"');
  });
});
