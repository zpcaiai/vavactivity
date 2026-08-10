import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const [kind, source, commandStatusSource] = process.argv.slice(2);
if (!kind || !source || !commandStatusSource) {
  throw new Error(
    "usage: write_playwright_evidence.mjs <kind> <source> <command-status>",
  );
}
const root = resolve(import.meta.dirname, "../..");
const sourcePath = resolve(root, source);
const commandStatusPath = resolve(root, commandStatusSource);
let commandStatus = {
  status: "NOT_RUN",
  reason: "command execution evidence is missing",
};
try {
  commandStatus = JSON.parse(await readFile(commandStatusPath, "utf8"));
} catch {
  // Missing or malformed command evidence remains fail-closed as NOT_RUN.
}
const payload = {
  status: commandStatus.status,
  kind,
  source,
  command_status_source: commandStatusSource,
  command_status: commandStatus,
  git_commit: execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: root,
    encoding: "utf8",
  }).trim(),
  checksum_sha256: null,
  generated_at: new Date().toISOString(),
};
if (commandStatus.status === "PASS") {
  try {
    await stat(sourcePath);
    const bytes = await readFile(sourcePath);
    payload.checksum_sha256 = createHash("sha256").update(bytes).digest("hex");
  } catch (error) {
    payload.status = "FAIL";
    payload.reason = `passed command did not produce evidence: ${error.message}`;
  }
} else if (!new Set(["NOT_RUN", "FAIL"]).has(commandStatus.status)) {
  payload.status = "FAIL";
  payload.reason = "invalid command execution status";
}
await mkdir(resolve(root, "build/ui"), { recursive: true });
await writeFile(resolve(root, `build/ui/${kind}.json`), JSON.stringify(payload, null, 2) + "\n");
if (payload.status === "FAIL") process.exitCode = 1;
