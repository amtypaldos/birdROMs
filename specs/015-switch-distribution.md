# Self-hosted Switch distribution and updates

## Status: COMPLETE

The same self-hosted birdROMs server must distribute both the existing handheld
client and a versioned Nintendo Switch archive. The Switch app checks its paired
server, downloads verified updates in the background, installs after releasing
SDL/ROMFS resources and restarts when supported. It preserves writable on-SD
config.json, its device token, ROM paths/mappings and ROM files.

Archive: switch/birdroms/birdroms.nro, version.json (platform, version,
nro_sha256, nro_size), and server.json containing server_url only. No device
token or runtime config.json. Existing users' config is never extracted or
replaced by an update. First-run seed settings remain in memory until a token
arrives, then use the existing Switch-safe config writer.

The server retains backward-compatible default muOS endpoints, adding
?platform=switch. Container CI pins and bundles both artifacts; startup publishes
both. Frontend Handheld page offers clear platform choice, correct install
instructions/download/version, shared pairing and concise controls/update help,
using existing product design tokens.

## Acceptance criteria

- [x] Existing handheld API/publishing tests pass unchanged.
- [x] Switch package validation rejects unsafe ZIPs, wrong hashes/layout/version and credentials.
- [x] Authenticated Switch info/download support browser sessions and Device tokens.
- [x] Personalized archives name the requesting server and exclude tokens/runtime config.
- [x] Both artifacts are bundled by reproducible image builds and installed at startup.
- [x] Frontend tests, lint and build pass; copy remains platform-correct and concise.
- [x] Switch update parser/versioning, streaming/cancel, ZIP/NRO/hash validation and safe replacement tests pass.
- [x] Seeded first run and writable config preservation are tested.
- [x] Clean Switch NRO + archive build and end-to-end server package checks pass.
- [x] Independent review findings are resolved; physical updater testing is honestly identified.

<!-- NR_OF_TRIES: 1 -->

## Verification record

- 615 backend tests passed on isolated PostgreSQL and GitHub CI.
- 161 frontend tests, lint and production build passed locally and in CI.
- Native host suites, four package CLI tests, clean Switch build and NRO checks passed.
- Real published images passed device-authenticated updater and desktop/mobile browser smoke tests with no API stubs.
- Production backend/worker/web pinned to 2026.11.02; services healthy, token-free HTTPS seed and default Go endpoint verified.
- Runtime JSON remained unchanged through staging/install and writable afterward.
- New updater installation/restart/power-loss behavior still requires physical Switch testing.
