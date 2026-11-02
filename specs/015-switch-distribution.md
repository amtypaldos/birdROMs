# Self-hosted Switch distribution and updates

## Status: IN PROGRESS

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

- [ ] Existing handheld API/publishing tests pass unchanged.
- [ ] Switch package validation rejects unsafe ZIPs, wrong hashes/layout/version and credentials.
- [ ] Authenticated Switch info/download support browser sessions and Device tokens.
- [ ] Personalized archives name the requesting server and exclude tokens/runtime config.
- [ ] Both artifacts are bundled by reproducible image builds and installed at startup.
- [ ] Frontend tests, lint and build pass; copy remains platform-correct and concise.
- [ ] Switch update parser/versioning, streaming/cancel, ZIP/NRO/hash validation and safe replacement tests pass.
- [ ] Seeded first run and writable config preservation are tested.
- [ ] Clean Switch NRO + archive build and end-to-end server package checks pass.
- [ ] Independent review findings are resolved; physical updater testing is honestly identified.

<!-- NR_OF_TRIES: 1 -->
