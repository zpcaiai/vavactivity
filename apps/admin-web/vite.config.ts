import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

// When deploying to Vercel the admin app lives under /admin/, so asset URLs
// must use that base.  Set VITE_BASE_PATH=/admin/ in the build environment
// (the scripts/vercel-build.mjs script sets this automatically).
const base = process.env.VITE_BASE_PATH ?? "/";

export default defineConfig({
  base,
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url))
    }
  },
  server: {
    port: 5174,
    strictPort: true
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/tests/setup.ts"]
  }
});
