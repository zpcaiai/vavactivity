import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("generated tokens include semantic themes, density, focus and safe areas", async () => {
  const tokens = JSON.parse(await readFile(new URL("../generated/tokens.json", import.meta.url)));
  assert.equal(tokens.version, "1.0.0");
  assert.deepEqual(Object.keys(tokens.semantic), ["light", "dark", "high-contrast"]);
  assert.equal(tokens.component.touchTarget.minimum, "2.75rem");
  assert.match(tokens.layout.safeArea.bottom, /safe-area-inset-bottom/u);
});

test("CSS carries text-equivalent semantic states and reduced motion", async () => {
  const css = await readFile(new URL("../generated/tokens.css", import.meta.url), "utf8");
  for (const token of ["color-success", "color-warning", "color-danger", "color-focus"]) {
    assert.match(css, new RegExp(`--vav-${token}:`, "u"));
  }
  assert.match(css, /prefers-reduced-motion/u);
});
