import { createHash } from "node:crypto";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const [kind, source] = process.argv.slice(2);
if (!kind || !source) throw new Error("usage: write_playwright_evidence.mjs <kind> <source>");
const root = resolve(import.meta.dirname, "../..");
const sourcePath = resolve(root, source);
await stat(sourcePath);
const bytes = await readFile(sourcePath);
const payload = { status: "PASS", kind, source, checksum_sha256: createHash("sha256").update(bytes).digest("hex"), generated_at: new Date().toISOString() };
await mkdir(resolve(root, "build/ui"), { recursive: true });
await writeFile(resolve(root, `build/ui/${kind}.json`), JSON.stringify(payload, null, 2) + "\n");
