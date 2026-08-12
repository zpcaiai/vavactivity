/**
 * Design-token guard.
 *
 * Page and component styles must resolve colour through semantic tokens so the
 * light, dark and high-contrast themes stay in sync. Literal hex values are
 * allowed only inside the token package itself.
 */
import { readdir, readFile } from "node:fs/promises";
import { join, extname } from "node:path";

const roots = process.argv.slice(2);
if (!roots.length) {
  console.error("usage: node scripts/check-design-tokens.mjs <dir> [dir...]");
  process.exit(2);
}

const EXTENSIONS = new Set([".css", ".vue"]);
const SKIP = new Set(["node_modules", "dist", "coverage", ".git", "generated"]);
const HEX = /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g;

async function* walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (SKIP.has(entry.name)) continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (EXTENSIONS.has(extname(entry.name))) yield full;
  }
}

const findings = [];
for (const root of roots) {
  for await (const file of walk(root)) {
    const source = await readFile(file, "utf8");
    const styles =
      extname(file) === ".vue"
        ? [...source.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/gu)].map((match) => match[1]).join("\n")
        : source;
    for (const match of styles.matchAll(HEX)) {
      findings.push(`${file}: ${match[0]}`);
    }
  }
}

if (findings.length) {
  console.error(`Hard-coded colours found in ${findings.length} place(s):`);
  for (const finding of findings) console.error(`  ${finding}`);
  process.exit(1);
}
console.log(`design token check passed for ${roots.join(", ")}`);
