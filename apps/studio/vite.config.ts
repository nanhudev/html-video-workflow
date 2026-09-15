import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API_TARGET = process.env.HVW_API ?? "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Every prefix the Studio actually calls has to be here. "/v1" was missing
    // while src/api.ts was already posting to /v1/videos, so the Generate page
    // worked in a production build and returned HTML in dev.
    proxy: {
      "/health": API_TARGET,
      "/system": API_TARGET,
      "/hardware": API_TARGET,
      "/providers": API_TARGET,
      "/projects": API_TARGET,
      "/jobs": API_TARGET,
      "/validate": API_TARGET,
      "/routing": API_TARGET,
      "/benchmarks": API_TARGET,
      "/v1": API_TARGET,
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
