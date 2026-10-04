/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.TRIM_API ?? "http://127.0.0.1:8000", changeOrigin: false } },
  },
  // assetsInlineLimit 0: never inline assets as data: URIs, which the production CSP (default-src 'self') blocks.
  build: { sourcemap: false, target: "es2022", assetsInlineLimit: 0 },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"] },
});
