import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Where the dev server proxies /api (ROMs and covers are never served from /media). Docker dev sets this to the backend service.
const apiProxyTarget = process.env.VITE_PROXY_TARGET || "http://localhost:8000";

// VITE_LAN=1 serves the dev UI to other devices on the network (a phone approving a handheld, the handheld itself).
// The proxy then keeps the browser's Host header, so server-built absolute URLs (the pairing qr_url) point at this
// dev server rather than at the backend's own address.
const lan = process.env.VITE_LAN === "1";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: lan ? true : undefined,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: !lan
      }
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    restoreMocks: true
  }
});
