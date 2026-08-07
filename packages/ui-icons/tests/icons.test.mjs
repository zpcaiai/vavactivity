import assert from "node:assert/strict"; import { readFile } from "node:fs/promises"; import test from "node:test";
test("every icon declares meaning or accessible-name policy", async () => { const value = JSON.parse(await readFile(new URL("../metadata/icons.json", import.meta.url))); for (const item of Object.values(value.icons)) assert.ok(item.meaning || item.requiredAccessibleName); });
