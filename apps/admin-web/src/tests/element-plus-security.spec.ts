import { describe, expect, it } from "vitest";

const adminVueSources = import.meta.glob<string>("../**/*.vue", {
  eager: true,
  import: "default",
  query: "?raw"
});

describe("Element Plus security boundary", () => {
  it("does not use the vulnerable el-link href surface", () => {
    for (const [path, source] of Object.entries(adminVueSources)) {
      expect(source, path).not.toMatch(/<el-link\b/iu);
    }
  });
});
