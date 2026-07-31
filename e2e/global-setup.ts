import { execFileSync } from "node:child_process";

function dockerCompose(args: string[]): string {
  return execFileSync("docker", ["compose", ...args], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  }).trim();
}

export default function globalSetup() {
  const output = dockerCompose([
    "exec",
    "-T",
    "redis",
    "redis-cli",
    "--raw",
    "--scan",
    "--pattern",
    "rate:*"
  ]);
  const keys = output.split(/\r?\n/u).filter(Boolean);
  for (let offset = 0; offset < keys.length; offset += 100) {
    dockerCompose([
      "exec",
      "-T",
      "redis",
      "redis-cli",
      "UNLINK",
      ...keys.slice(offset, offset + 100)
    ]);
  }
}
