# Self-hosted Switch Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve versioned, token-free Switch archives from birdROMs and safely update the native app.

**Architecture:** Existing Django handheld endpoints accept platform=switch and publish a separately pinned ZIP. A background C++ updater authenticates to the paired server, verifies the NRO against metadata and a manifest, stages beside the actual running executable, then swaps only after cleanup. The React Handheld page stays within existing design tokens and explains the two installation paths.

**Tech Stack:** Django/DRF/PostgreSQL, React/Vite/Yarn, Docker, C++17/libnx/SDL2/curl/minizip/PicoSHA2.

**Spec:** specs/015-switch-distribution.md

## Global Constraints

- No device token or runtime config.json in downloadable archives.
- Writable SD config and ROMs are preserved; first-run app writes config only after token receipt.
- Default Go endpoints and existing release pipelines remain compatible.
- Updates come from the paired server, not GitHub; native HTTPS verification stays enabled.
- SDL remains responsive; self replacement happens after ROMFS and SDL close.
- Shared version: vYYYY.MM.DD[.N], initial updater version v2026.11.02.

## Review Focus

- Existing config and tokens survive seed installs and updates (storage integration).
- A personalized ZIP hash differs from stored archive: verify NRO digest and manifest, not whole personalized ZIP hash (updater).
- Switch rename cannot overwrite; apply needs backup/rollback after closing resources (updater/runtime).
- Three- and four-component date versions compare correctly; older versions never install (updater).
- Platform switching cannot display stale download data; default Go requests stay unchanged (frontend).

### Task 1: Django/package/image support — storage agent

Files: backend/apps/roms/{handheld,handheld_views,test_switch_handheld}.py,
management commands, settings, backend startup, docker-publish.yml, switch-version.
Interfaces: ?platform=switch metadata {available,platform,version,filename,size,sha256,nro_sha256,nro_size,published_at}; download personalized strict ZIP.
- [x] Write failing tests, observe legacy platform request fails expected behavior.
- [x] Implement strict package validation, publishing and bundling.
- [x] Run focused PostgreSQL tests (26 passed).
- [x] Run full backend tests and independent review (615 tests passed; review fixes re-reviewed).

### Task 2: Frontend install flow — UI agent

Files: frontend/src/HandheldView.jsx, api/client.js, scoped styles and tests.
- [x] Write platform-specific behavior tests before implementation.
- [x] Verify red/green, full tests, lint and build with Node24 tools (161 passed).
- [x] Apply Product Design existing-code workflow, critique and desktop/mobile Playwright QA.
- [x] Independent review; copy/CSS issues fixed and re-reviewed.

### Task 3: Native updater engine — API agent

Files: handheld repo switch/{include,source}/update, API client extensions and tests/update*.
- [x] Implement background check/download, bounded ZIP/NRO/hash validation and safe staging/apply.
- [x] Verify date-version regression red/green (earlier engine work predated explicit skill request).
- [x] Host suites, clean cross-build, independent review and regression fixes verified.

### Task 4: Runtime integration, seed, archive and tests — coordinator

Files: handheld switch/source/{main,ui/app}.cpp, config storage, package scripts/build/tests/docs.
- [x] Seed/UI policy regressions observed red then green; config preservation verified.
- [x] Automatic paired-server checking; B skips, ZL retries; update outcome returned to main.
- [x] Resource cleanup precedes installation; restart or reopen fallback implemented.
- [x] Real NRO packaged, personalized by Django, staged/installed by native host code; config remains writable.
- [ ] Run final native suites, Switch build, frontend/backend checks and image build.

### Task 5: Review and delivery — coordinator + fresh reviewer

- [ ] Review cross-repository contract, security, rollback/config preservation, frontend content and image pins.
- [ ] Resolve Important/Critical findings with regression tests and re-review.
- [ ] Record verification, history/completion logs and release artifacts without claiming physical updater verification.
