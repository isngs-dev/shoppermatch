import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the React app runs on :5173 and proxies backend routes to FastAPI on
// :8000 so the browser sees a single origin (no CORS, relative URLs work in dev
// and in production where FastAPI serves the built SPA).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/r": { target: "http://localhost:8000", changeOrigin: true },
      "/track": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
