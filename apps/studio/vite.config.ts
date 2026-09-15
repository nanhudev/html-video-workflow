import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API_TARGET = process.env.HVW_API ?? "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
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
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
