/**
 * Vercel monorepo build script
 *
 * Builds user-web and admin-web, then merges their dist outputs into a single
 * directory that Vercel serves as the deployment output:
 *
 *   dist/public/           ← user-web (serves /)
 *   dist/public/admin/     ← admin-web (serves /admin/*)
 *
 * The root vercel.json rewrites handle SPA routing for each app.
 */

import { execSync } from "node:child_process";
import {
  cpSync,
  mkdirSync,
  readdirSync,
  rmSync,
} from "node:fs";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const out = join(root, "dist", "public");

function run(cmd, cwd, extraEnv = {}) {
  console.log(`\n▶ ${cmd} (in ${cwd})`);
  execSync(cmd, {
    cwd,
    stdio: "inherit",
    env: { ...process.env, ...extraEnv }
  });
}

// ── Clean output directory ────────────────────────────────────────────────────
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

// ── Build user-web ────────────────────────────────────────────────────────────
const userWebDir = join(root, "apps", "user-web");
run("pnpm exec vue-tsc -b && pnpm exec vite build", userWebDir);

// Copy user-web dist → dist/public/
cpSync(join(userWebDir, "dist"), out, { recursive: true });
console.log("✔ user-web copied to dist/public/");

// ── Build admin-web ───────────────────────────────────────────────────────────
const adminWebDir = join(root, "apps", "admin-web");
run("pnpm exec vue-tsc -b && pnpm exec vite build", adminWebDir, {
  VITE_BASE_PATH: "/admin/"
});

// Copy admin-web dist → dist/public/admin/
const adminOut = join(out, "admin");
mkdirSync(adminOut, { recursive: true });
cpSync(join(adminWebDir, "dist"), adminOut, { recursive: true });
console.log("✔ admin-web copied to dist/public/admin/");

// ── Summary ───────────────────────────────────────────────────────────────────
function listFiles(dir, prefix = "") {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      listFiles(join(dir, entry.name), `${prefix}${entry.name}/`);
    } else {
      console.log(`  ${prefix}${entry.name}`);
    }
  }
}

console.log("\n📦 Output contents (dist/public/):");
listFiles(out);
console.log("\n✅ Vercel build complete.");
