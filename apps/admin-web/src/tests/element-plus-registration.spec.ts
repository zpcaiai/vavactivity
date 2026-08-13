import { describe, expect, it } from "vitest";

const mainSources = import.meta.glob<string>("../main.ts", {
  eager: true,
  import: "default",
  query: "?raw"
});
const mainSource = Object.values(mainSources)[0] ?? "";

const adminVueSources = import.meta.glob<string>("../**/*.vue", {
  eager: true,
  import: "default",
  query: "?raw"
});

const stylePackageOverrides: Record<string, string> = {
  "checkbox-group": "checkbox",
  "collapse-item": "collapse",
  "descriptions-item": "descriptions",
  "form-item": "form",
  option: "select",
  "tab-pane": "tabs",
  "table-column": "table"
};

function componentName(tag: string) {
  return `El${tag.split("-").map((part) =>
    `${part.charAt(0).toUpperCase()}${part.slice(1)}`
  ).join("")}`;
}

function usedElementPlusTags() {
  return [...new Set(
    Object.values(adminVueSources).flatMap((source) =>
      [...source.matchAll(/<el-([a-z0-9-]+)/giu)].map((match) => match[1] ?? "")
    ).filter(Boolean)
  )].sort();
}

describe("Element Plus component registration", () => {
  it("registers every Element Plus component used by an admin template", () => {
    const registrationBlock = mainSource.match(
      /app\.use\(router\);\s*\[([\s\S]*?)\]\.forEach/u
    )?.[1];

    expect(registrationBlock).toBeDefined();
    for (const tag of usedElementPlusTags()) {
      const component = componentName(tag);
      expect(registrationBlock, component).toMatch(
        new RegExp(`\\b${component}\\b`, "u")
      );
    }
  });

  it("loads styles for every Element Plus component used by an admin template", () => {
    const stylePackages = new Set(
      usedElementPlusTags().map((tag) => stylePackageOverrides[tag] ?? tag)
    );

    for (const stylePackage of stylePackages) {
      expect(mainSource, stylePackage).toContain(
        `import "element-plus/es/components/${stylePackage}/style/css";`
      );
    }
  });
});
