/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // In development the API runs on port 8000; the browser only talks to Vite
    proxy: { "/v1": "http://localhost:8000" },
  },
  build: {
    // MapLibre alone is about 1.1 MB (300 kB gzipped). It is split into its own chunk that
    // loads only with the map, so warn above that instead of the default 500 kB.
    chunkSizeWarningLimit: 1200,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
