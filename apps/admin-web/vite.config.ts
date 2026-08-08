import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

// On Vercel the admin app is served under /admin/; Vite's `base` must match
// so that asset URLs (JS/CSS) resolve correctly.
// VERCEL=1 is injected automatically by Vercel for every build.
const base = process.env.VITE_BASE_PATH ?? (process.env.VERCEL === "1" ? "/admin/" : "/");

export default defineConfig({
  base,
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-element-plus": ["element-plus", "@element-plus/icons-vue"],
          "vendor-vue": ["vue", "vue-router", "pinia"]
        }
      }
    }
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url))
    }
  },
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000",
        changeOrigin: true
      }
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/tests/setup.ts"]
  }
});
