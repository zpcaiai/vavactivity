/**
 * scripts/vercel-merge.mjs
 *
 * Post-build merge step for Vercel deployments.
 * Assumes both SPAs have already been built by the recursive `pnpm build`.
 *
 * Output layout (matches vercel.json → outputDirectory: "dist"):
 *   dist/           ← user-web  (serves /)
 *   dist/admin/     ← admin-web (serves /admin/*)
 */

import { cpSync, mkdirSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const out = join(root, "dist");

console.log("▶ Merging SPA outputs into dist/ …");

// Clean and recreate output root
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

// user-web → dist/
cpSync(join(root, "apps", "user-web", "dist"), out, { recursive: true });
console.log("  ✔ user-web  → dist/");

// admin-web → dist/admin/
const adminOut = join(out, "admin");
mkdirSync(adminOut, { recursive: true });
cpSync(join(root, "apps", "admin-web", "dist"), adminOut, { recursive: true });
console.log("  ✔ admin-web → dist/admin/");

console.log("✅ Merge complete.");
