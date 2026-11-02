# Self-hosted Switch distribution

Default handheld endpoints remain muOS-compatible; platform=switch selects a
separate versioned ZIP. Its runtime config/token are never packaged. Server
seeds contain only the requesting server origin. Publisher and native client
share ZIP/NRO/compression/version limits; layout validation prevents publishing
archives the updater cannot consume.

Switch installation runs after SDL/font/worker/ROMFS cleanup because libnx
holds the running NRO open. A launchable previous NRO supports rollback. Failed
updates wait for explicit retry. The writable runtime JSON uses its existing
Switch-safe replacement/recovery path and is preserved across updates.

Handheld page uses existing product tokens with platform selection, short
install steps and shared pairing. Product Design and Superpowers workflows
informed implementation, red/green regressions and independent review.

Verification: 615 Django tests; 161 frontend tests; lint/build; all native host
suites and four packager tests; clean NRO build; published multi-arch images;
real browser login/download and native device-authenticated update smoke tests.
Production pinned to 2026.11.02, with correct token-free HTTPS seed and existing
admin access verified. Physical Switch updater/restart testing is not claimed.

A pre-existing PWA registerSW.js omission remains outside this change.
