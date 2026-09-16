import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development Vite serves the page and forwards /api to a running NASQuay.
// NASQUAY_DEV_API overrides where that is.
const api = process.env.NASQUAY_DEV_API ?? "http://127.0.0.1:9999";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    proxy: {
      "/api": { target: api, changeOrigin: false },
    },
  },
});
