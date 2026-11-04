import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the React app runs on :5173 and proxies backend routes to FastAPI on
// :8000 so the browser sees a single origin (no CORS, relative URLs work in dev
// and in production where FastAPI serves the built SPA). Set API_TARGET when
// the backend runs elsewhere (e.g. another project already owns :8000).
const API_TARGET = process.env.API_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
      "/r": { target: API_TARGET, changeOrigin: true },
      "/track": { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
