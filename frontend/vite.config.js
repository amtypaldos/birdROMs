import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Where the dev server proxies /api (ROMs and covers are never served from /media). Docker dev sets this to the backend service.
const apiProxyTarget = process.env.VITE_PROXY_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true
      }
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    restoreMocks: true
  }
});
