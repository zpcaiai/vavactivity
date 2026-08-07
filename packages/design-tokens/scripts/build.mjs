import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = async (name) => JSON.parse(await readFile(resolve(root, `src/${name}/tokens.json`), "utf8"));
const [primitive, semantic, component, layout, motion, density] = await Promise.all(
  ["primitive", "semantic", "component", "layout", "motion", "density"].map(source)
);
const resolveReference = (value) => {
  if (typeof value !== "string" || !/^\{[^}]+\}$/u.test(value)) return value;
  return value.slice(1, -1).split(".").reduce((cursor, key) => cursor[key], primitive);
};
const kebab = (value) => value.replace(/([a-z0-9])([A-Z])/gu, "$1-$2").toLowerCase();
const flatten = (value, prefix = [], output = {}) => {
  for (const [key, item] of Object.entries(value)) {
    if (item && typeof item === "object" && !Array.isArray(item)) flatten(item, [...prefix, key], output);
    else output[prefix.concat(key).map(kebab).join("-")] = resolveReference(item);
  }
  return output;
};
const base = flatten({ ...primitive, component, layout, motion });
const themeValues = Object.fromEntries(Object.entries(semantic).map(([name, value]) => [name, flatten(value)]));
const densityValues = Object.fromEntries(Object.entries(density).map(([name, value]) => [name, flatten({ density: value })]));
const declarations = (values) => Object.entries(values).sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => `  --vav-${key}: ${value};`).join("\n");
const css = [
  `/* Generated from design-token-manifest.yaml. Do not edit. */\n:root, [data-vav-theme="light"] {\n${declarations({ ...base, ...themeValues.light, ...densityValues.comfortable })}\n}`,
  `[data-vav-theme="dark"] {\n${declarations(themeValues.dark)}\n}`,
  `[data-vav-theme="high-contrast"] {\n${declarations(themeValues["high-contrast"])}\n}`,
  `[data-vav-density="compact"] {\n${declarations(densityValues.compact)}\n}`,
  `@media (prefers-reduced-motion: reduce) {\n  :root { --vav-duration-fast: 0ms; --vav-duration-normal: 0ms; --vav-duration-slow: 0ms; }\n}`
].join("\n\n") + "\n";
const generated = { version: "1.0.0", primitive, semantic, component, layout, motion, density };
const ts = `/* Generated. */\nexport const tokens = ${JSON.stringify(generated, null, 2)} as const;\nexport type VavTheme = keyof typeof tokens.semantic;\nexport type VavDensity = keyof typeof tokens.density;\n`;
const scss = Object.entries(base).sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => `$vav-${key}: ${value};`).join("\n") + "\n";
await mkdir(resolve(root, "generated"), { recursive: true });
await Promise.all([
  writeFile(resolve(root, "generated/tokens.css"), css),
  writeFile(resolve(root, "generated/tokens.json"), JSON.stringify(generated, null, 2) + "\n"),
  writeFile(resolve(root, "generated/tokens.ts"), ts),
  writeFile(resolve(root, "generated/tokens.scss"), scss)
]);
