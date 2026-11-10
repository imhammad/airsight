/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { mockApi } from "./e2e/mock-api.ts";

export default defineConfig({
  // MOCK_API=1 (npm run preview:mock) answers /v1 itself, for the browser checks in CI
  plugins: [react(), process.env.MOCK_API === "1" && mockApi()],
  server: {
    // In development the API runs on port 8000; the browser only talks to Vite
    proxy: { "/v1": "http://localhost:8000" },
  },
  preview: {
    port: 4173,
    strictPort: true,
  },
  build: {
    // MapLibre alone is about 1.1 MB (300 kB gzipped). It is split into its own chunk that
    // loads only with the map, so warn above that instead of the default 500 kB.
    chunkSizeWarningLimit: 1200,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    // The browser tests in e2e/ run with Playwright, not Vitest
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
