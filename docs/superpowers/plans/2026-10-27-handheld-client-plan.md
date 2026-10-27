# birdROMs Handheld Client — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship a v1 muOS handheld client that pairs to a birdROMs instance (QR / phone-approve), lets a friend browse Platforms + owner-created Playlists on a controller, and downloads ROMs into the correct per-system folders — plus the small birdROMs server additions that back it.

**Architecture:** Two parts, two repos. **Part A** adds device pairing, playlists, a device-friendly listing API, and open upload to the existing Django/DRF backend (`birdROMs` repo). **Part B** is a single static ARM64 **Go + SDL2** binary packaged as a muOS `.muxzip` app (`birdroms-handheld` repo). The client talks to the Part A API over HTTPS with a scoped device token. ROCKNIX is a later wrapper, out of v1 scope.

**Tech Stack:** Part A — Python 3.11+, Django 5, DRF (+ a QR-approve page in the React frontend). Part B — Go (static `GOARCH=arm64`), SDL2 (`go-sdl2`), a Go QR encoder, bundled Chakra Petch TTF.

**Spec:** `docs/superpowers/specs/2026-10-27-handheld-client-design.md` (read it alongside this plan).

## Global Constraints

- **Part A runs in the `birdROMs` repo; Part B runs in the `birdroms-handheld` repo** (github.com/amtypaldos/birdroms-handheld). They can execute as two separate SDD passes; do Part A first (B depends on its API).
- Part A: Postgres everywhere; task defs via the Huey seam if any; every code change has a test; match existing birdROMs style; no secrets committed. Device tokens are **scoped and revocable**.
- Part B: one **static** `arm64` binary (no runtime deps on the device); verify every device-specific fact (folder names, screen size, input, `.muxzip` layout, game-list refresh) **empirically over SSH** before coding against it — never guess. Visual parity with the web UI (dark/neon, cover-art-forward, Chakra Petch).
- **Permissions (v1):** any authenticated user can upload and create playlists (RBAC deferred).
- Device/test loop uses the maintainer's RG40XX-V (muOS, upgraded) + RG35XX+ over SSH/SFTP; the device LAN IP + SSH access are provided at execution time.

## Review Focus

Inputs the design implies but task happy-paths won't catch — each pinned to a task:
1. **Pairing abuse/expiry** — a pairing code must expire, be single-use, and a device token must be revocable; polling an unapproved/expired code must not leak access. *(Task A1)*
2. **Flaky wifi mid-download** — a dropped/half download must be resumable or safely re-fetched, never leaving a corrupt ROM in the games folder. *(Task B6)*
3. **Wrong-folder / unknown platform** — a ROM whose platform has no mueOS folder mapping must go somewhere safe + visible, not vanish or crash. *(Task B6)*
4. **Low memory / large library** — browsing thousands of ROMs + cover art on a constrained device must page/lazy-load, not OOM. *(Tasks A4, B5)*
5. **Device token on a shared card** — the stored token must be the only secret on the card and be re-pairable/revocable if the card is lost. *(Tasks A1, B3)*

---

# Part A — birdROMs server additions (repo: `birdROMs`)

### Task A1: Device pairing — DeviceToken model + endpoints

**Files:** Create `backend/apps/accounts/pairing.py`; modify `apps/accounts/models.py`, `urls.py`, `serializers.py`; new migration; Test: `apps/accounts/tests.py`.

**Interfaces / Produces:**
- `DeviceToken` model: `user` FK, `name`, `token` (random, hashed-at-rest or opaque), `created_at`, `last_used_at`, `revoked` bool.
- `PairingRequest` model (ephemeral): `code` (short, e.g. 6 chars), `qr_payload` (approve URL), `created_at`, `expires_at` (e.g. 5 min), `approved_by` FK nullable, `device_token` FK nullable, `consumed` bool.
- `POST /api/devices/pair/start` (unauth) → `{code, qr_url, expires_at}`.
- `POST /api/devices/pair/approve` (**authed**, from the phone) `{code}` → mints a `DeviceToken` for the user, attaches it to the request.
- `GET /api/devices/pair/poll?code=…` (unauth) → `202` while pending, `200 {device_token}` once approved (single-use), `410` when expired/consumed.
- A DRF auth class accepting a `DeviceToken` (header `Authorization: Device <token>`), rejecting revoked ones.

- [ ] **Step 1: Failing tests** — `test_pair_start_returns_code_qr_expiry`; `test_approve_requires_auth_and_mints_token`; `test_poll_pending_then_returns_token_once` (second poll → 410); `test_expired_code_cannot_be_approved_or_polled`; `test_device_token_auth_accepted_and_revocable`. *(Review Focus #1, #5)*
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** models + migration + the three endpoints + the Device auth class.
- [ ] **Step 4: Run → PASS** (`cd backend && uv run python manage.py test`).
- [ ] **Step 5: Commit** — `feat: device pairing (QR/phone-approve) + revocable device tokens`.

### Task A2: "Approve device" web page (React)

**Files:** Modify `frontend/src/App.jsx`, `frontend/src/api/client.js`, `frontend/src/App.test.jsx`.

**Interfaces:** A route/page (e.g. `/pair?code=…` or an in-app panel) where a signed-in user sees the code and an **Approve** button calling `api.approveDevice(code)`; shows success/expired states.

- [ ] **Step 1: Failing test** — `test_approve_device_page_calls_api_and_shows_result` (mock api; approve → success; expired → message).
- [ ] **Step 2: Run (`PATH="$HOME/.local/share/mise/shims:$PATH" yarn test`) → FAIL.**
- [ ] **Step 3: Implement** the approve UI + `api.approveDevice`.
- [ ] **Step 4: Run** `yarn test && yarn lint && yarn build` → PASS.
- [ ] **Step 5: Commit** — `feat: approve-device page for handheld pairing`.

### Task A3: Playlist model + API

**Files:** Create `backend/apps/roms/playlists.py` (views/serializers) or extend existing; modify `models.py`, `urls.py`; new migration; Test: `apps/roms/tests.py`.

**Interfaces / Produces:**
- `Playlist` model: `name`, `created_by` FK, `created_at`, M2M/through `PlaylistItem(playlist, rom, order)`.
- `GET /api/playlists/` (list), `GET /api/playlists/{id}/` (with ordered roms), `POST /api/playlists/` + item management — **any authenticated user** can create/edit their own.

- [ ] **Step 1: Failing tests** — `test_any_authed_user_creates_playlist`; `test_playlist_detail_returns_ordered_roms`; `test_non_owner_cannot_edit_others_playlist`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** model + migration + viewset + ordering.
- [ ] **Step 4: Run → PASS** + `makemigrations --check`.
- [ ] **Step 5: Commit** — `feat: user-created playlists`.

### Task A4: Device-friendly listing API

**Files:** Modify `backend/apps/roms/views.py`, `serializers.py`; Test: `apps/roms/tests.py`.

**Interfaces / Produces:** a compact, paginated listing the client needs with minimal round-trips:
- `GET /api/roms/?fields=device` (or a dedicated serializer) returning per ROM: `id, title, platform, extension, size_bytes, cover_url`. Paginated (page size tuned for the device). Reuse the existing search/platform filters.
- Confirm `GET /api/roms/platforms/` is sufficient (distinct platforms + counts).

- [ ] **Step 1: Failing tests** — `test_device_listing_has_size_and_cover_url`; `test_device_listing_paginates`; `test_platforms_endpoint_counts`. *(Review Focus #4)*
- [ ] **Step 2–5:** implement, run → PASS, commit — `feat: device-friendly ROM listing (size + cover url)`.

### Task A5: Open upload permission (v1)

**Files:** Modify `backend/apps/roms/permissions.py` / `views.py`; Test: `apps/roms/tests.py`.

**Interfaces:** Relax ROM create (upload) from `super_admin`-only to **any authenticated user** (RBAC deferred). Download/list already authed.

- [ ] **Step 1: Failing test** — `test_any_authed_user_can_upload` (readonly-group user now gets 201). Update the existing "readonly cannot create" test to reflect the new policy.
- [ ] **Step 2–5:** implement, run → PASS, commit — `feat: allow any authenticated user to upload (RBAC deferred)`.

---

# Part B — Go/SDL handheld client (repo: `birdroms-handheld`)

> Clone the empty repo first; scaffold lands in Task B2. Device-specific facts from B1 feed B6/B7.

### Task B1: On-device verification (muOS) — SSH recon

**Files:** Create `docs/device-notes-muos.md` in the client repo.

**Produces (document the verified facts):** exact `roms/<system>` folder names per platform on the upgraded muOS (SD1 `/mnt/mmc` vs SD2 `/mnt/sdcard`); screen resolution + input device/button mapping; the `.muxzip` "application" layout + launch-script convention for this muOS version; how the games list is refreshed after adding a ROM; whether SDL2 libs are present or must be bundled.

- [ ] **Step 1:** Over SSH/SFTP to the RG40XX-V: list the real ROM folders, check `/opt/muos` archive scripts for the app conventions, note resolution/input, test adding a dummy file and refreshing the list.
- [ ] **Step 2:** Write `docs/device-notes-muos.md` with exact paths/names/values.
- [ ] **Step 3: Commit** — `docs: verified muOS device facts (folders, muxzip, input, refresh)`.
  *(No code; this is the empirical ground truth B6/B7 build on. Blocked until the device is upgraded + reachable.)*

### Task B2: Repo scaffold + static ARM64 build + on-device "hello SDL"

**Files:** `go.mod`, `main.go`, `Makefile`/build script, `README.md`.

**Produces:** a Go module that cross-compiles to a **static arm64** binary; an SDL2 fullscreen window that opens, shows "birdROMs" in Chakra Petch on the dark/neon theme, reads gamepad input, and exits on a button — **deployed to the device over SFTP and confirmed running over SSH**.

- [ ] **Step 1:** Scaffold module + build to arm64; unit-test the build produces a static binary (CI check) and a trivial pure-Go unit (e.g. version string).
- [ ] **Step 2:** Implement the SDL window + font + input loop.
- [ ] **Step 3: On-device smoke** — SFTP the binary, run over SSH, confirm window + input on the RG40XX-V; record result in the report.
- [ ] **Step 4: Commit** — `feat: SDL hello-world running on muOS (static arm64)`.

### Task B3: Config/token store + API client

**Files:** `internal/config/…`, `internal/api/…`, `*_test.go`.

**Interfaces / Produces:** `config` loads/saves `{server_url, device_token}` to a file on the card; `api.Client` with `ListPlatforms()`, `ListROMs(platform, page)`, `ListPlaylists()`, `GetPlaylist(id)`, `DownloadROM(id, w, progressCb)` using `Authorization: Device <token>`.

- [ ] **Step 1: Failing Go tests** against an `httptest` mock server — auth header set; listing parsed; pagination; download streams bytes + reports progress; 401 on revoked token surfaced. *(Review Focus #5)*
- [ ] **Step 2–4:** implement, `go test ./...` PASS, commit — `feat: config store + birdROMs API client`.

### Task B4: Pairing screen (QR + short code + poll)

**Files:** `internal/pair/…`, `ui/pair…`, `*_test.go`.

**Interfaces / Produces:** on first run (no token), call `POST /pair/start`, render the **QR** (encoding `qr_url`) + the short code on screen, then **poll** `/pair/poll` until it returns a token; store it (Task B3) and proceed. Backoff + timeout + a retry on expiry.

- [ ] **Step 1: Failing tests** — poll loop: pending→token happy path; expiry→restart; the QR payload encodes the server-provided URL. Mock the pairing endpoints. *(Review Focus #1)*
- [ ] **Step 2–4:** implement (QR render in SDL), test, commit — `feat: QR/phone-approve pairing screen`.

### Task B5: Browse UI — platforms, playlists, cover grid

**Files:** `ui/browse…`, theme tokens, `*_test.go` (for the non-SDL logic).

**Interfaces / Produces:** home with **Playlists** + **Platforms**; platform/playlist → a controller-navigable **cover-art grid** (lazy-loaded covers, paged) matching the web UI theme; select → add to the download queue. Unit-test the list/selection/paging state model separately from SDL rendering.

- [ ] **Step 1: Failing tests** — the browse state model: navigation, selection set, lazy page requests, empty states. *(Review Focus #4)*
- [ ] **Step 2–3:** implement the model + SDL views; **on-device smoke** (navigate, see covers) on the RG40XX-V.
- [ ] **Step 4: Commit** — `feat: browse platforms + playlists (cover grid)`.

### Task B6: Download manager + folder mapping

**Files:** `internal/download/…`, `internal/platforms/muos_folders.go`, `*_test.go`.

**Interfaces / Produces:** a queue that downloads selected ROMs **one/few at a time**, shows per-item progress, is **resumable/atomic** (write to a temp file, fsync, rename into place — never a half file in the games folder), and writes into the correct `roms/<system>` folder via the verified map from B1; **unknown platform → a safe visible fallback folder + a flag**, never a crash or silent drop; triggers the muOS game-list refresh.

- [ ] **Step 1: Failing tests** — platform→folder map (verified names from B1); atomic write (interrupted download leaves no file in the target); resume/retry; unknown-platform fallback. *(Review Focus #2, #3)*
- [ ] **Step 2–3:** implement; **on-device smoke** — download a real ROM, confirm it lands in the right folder and appears in the muOS list after refresh.
- [ ] **Step 4: Commit** — `feat: resumable download manager + muOS folder mapping`.

### Task B7: muOS `.muxzip` packaging + end-to-end

**Files:** `packaging/muos/…`, build/release script.

**Produces:** a `.muxzip` (per B1's verified layout) that installs the binary as a muOS **application**; a release script that builds + packages. **End-to-end on device:** install the `.muxzip`, launch from the Apps menu, pair via QR, browse, download, play.

- [ ] **Step 1:** Build the `.muxzip` per the verified spec; validate its structure.
- [ ] **Step 2: On-device end-to-end** — install, launch, pair, download, confirm a game runs on the RG40XX-V; record in the report.
- [ ] **Step 3: Commit** — `feat: muOS .muxzip packaging + end-to-end`.

---

## Self-Review

**Spec coverage:** pairing/QR (A1,A2,B4) ✓ · playlists (A3, surfaced B5) ✓ · device listing w/ covers+size (A4) ✓ · open upload (A5) ✓ · Go+SDL static binary (B2) ✓ · browse+download into folders (B5,B6) ✓ · `.muxzip` packaging (B7) ✓ · web-UI visual parity (B2,B5) ✓ · on-device SSH verification first (B1) ✓ · muOS-only v1, ROCKNIX deferred ✓.

**Review Focus:** #1→A1/B4, #2→B6, #3→B6, #4→A4/B5, #5→A1/B3 — each has a named test.

**Type/interface consistency:** `DeviceToken` + `Authorization: Device <token>` defined in A1, consumed by B3/B4; the device listing fields (A4) are what B3's `ListROMs` parses; the folder map (B6) uses B1's verified names.

**Ordering/dependencies:** A1→A4 are backend, independent of the device (can run while the muOS upgrade is in progress). B1 (device recon) gates B6/B7's exact values but B2–B5 can proceed in parallel once B1's basics (folders, build, input) are known. Execute **Part A first** (B's pairing/listing/download need its API), with **B1 as the very first client task** the moment the device is reachable.

**Proportion:** interfaces + test names, no full bodies — plan is shorter than the code it describes.
