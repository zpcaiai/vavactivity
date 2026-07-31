import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";

const directory = resolve(process.argv[2] ?? "apps/user-web/src/i18n/locales");
const files = (await readdir(directory))
  .filter((name) => name.endsWith(".json"))
  .sort();

if (files.length < 2) {
  throw new Error(`Expected at least two locale files in ${directory}`);
}

function flatten(value, prefix = "", output = new Map()) {
  for (const [key, child] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (child && typeof child === "object" && !Array.isArray(child)) {
      flatten(child, path, output);
    } else {
      output.set(path, String(child));
    }
  }
  return output;
}

function placeholders(value) {
  return [...value.matchAll(/\{([A-Za-z0-9_]+)\}/g)]
    .map((match) => match[1])
    .sort()
    .join(",");
}

const locales = new Map();
for (const file of files) {
  locales.set(file, flatten(JSON.parse(await readFile(resolve(directory, file), "utf8"))));
}

const [referenceFile, reference] = locales.entries().next().value;
for (const [file, values] of locales) {
  const missing = [...reference.keys()].filter((key) => !values.has(key));
  const extra = [...values.keys()].filter((key) => !reference.has(key));
  const placeholderMismatch = [...reference.keys()].filter(
    (key) => placeholders(reference.get(key)) !== placeholders(values.get(key) ?? "")
  );
  if (missing.length || extra.length || placeholderMismatch.length) {
    throw new Error(
      `${file} differs from ${referenceFile}: missing=${missing.join(",")} ` +
        `extra=${extra.join(",")} placeholders=${placeholderMismatch.join(",")}`
    );
  }
}

console.log(`i18n parity verified for ${files.length} locales and ${reference.size} keys`);
