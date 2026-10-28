import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// Where the dev server proxies /api (ROMs and covers are never served from /media). Docker dev sets this to the backend service.
const apiProxyTarget = process.env.VITE_PROXY_TARGET || "http://localhost:8000";

// VITE_LAN=1 serves the dev UI to other devices on the network (a phone approving a handheld, the handheld itself).
// The proxy then keeps the browser's Host header, so server-built absolute URLs (the pairing qr_url) point at this
// dev server rather than at the backend's own address.
const lan = process.env.VITE_LAN === "1";

export default defineConfig({
  plugins: [
    react(),
    // Installable app + offline shell only. The service worker precaches the build output and nothing else:
    // no runtime caching, so API responses, ROMs and covers always come from the network.
    VitePWA({
      registerType: "autoUpdate",
      strategies: "generateSW",
      includeAssets: ["icon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "birdROMs",
        short_name: "birdROMs",
        description: "Private retro ROM sharing hub",
        display: "standalone",
        start_url: "/",
        scope: "/",
        theme_color: "#0b0a12",
        background_color: "#0b0a12",
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" }
        ]
      },
      workbox: {
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api/, /^\/admin/, /^\/static/],
        globPatterns: ["**/*.{js,css,html,svg,png,woff2,webmanifest}"],
        runtimeCaching: []
      }
    })
  ],
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
