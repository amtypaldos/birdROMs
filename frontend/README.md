# birdROMs frontend

React 18 + Vite 5, Yarn Berry (PnP). `yarn dev | build | preview | test | lint`.

## PWA (installable app + offline shell)

Built with `vite-plugin-pwa` (generateSW, `registerType: "autoUpdate"`, config in `vite.config.js`).

- The service worker precaches the build output only (shell, JS, CSS, fonts, icons). There is **no runtime caching**:
  `/api`, ROM downloads and cover art always hit the network. Offline, the shell loads and shows an
  "You're offline" notice; no data is cached or shown.
- `/api`, `/admin` and `/static` are excluded from the navigation fallback.
- nginx serves `sw.js`, `workbox-*.js`, `registerSW.js` and `manifest.webmanifest` with `Cache-Control: no-cache`;
  hashed `/assets/` stay immutable.
- **HTTPS required:** service workers and installability only work on HTTPS or `localhost`. Over plain
  `http://192.168.x.x` a phone cannot install the app. To test install on a phone, put an HTTPS tunnel or
  proxy in front (LAN dev over http is fine for everything except install and the service worker).
- To check locally: `yarn build && yarn preview --port 4174`, then Chrome DevTools, Application tab
  (manifest, service worker) and Lighthouse on `http://localhost:4174`.

### Icons

`public/icon.svg` is the source (the handheld bird glyph, neon on `#0b0a12`, bird inside the maskable safe zone).
The PNGs (`icon-192`, `icon-512`, `icon-maskable-512`, `apple-touch-icon`) are committed and were rendered once with
`scripts/render-icons.sh` (headless Google Chrome). Re-run it only after editing `icon.svg`; it is not part of the build.
