# birdROMs Handheld Client (muOS first) — Design

Date: 2026-10-27
Status: APPROVED (2026-10-27)

## Intent / Why

birdROMs is a private, share-with-friends ROM hub: an owner uploads once, friends sign in and
download. The missing half is getting those ROMs onto the handheld friends actually play on.
Loading an SD card full of games by hand is slow and annoying. This project is an **on-device,
controller-driven client** that lets a friend **browse and pick** games (and grab owner-curated
**playlists**) straight on their muOS handheld, downloading them into the right folders ready to
play. This is birdROMs' differentiator versus RomM's scan-your-own-library model, and it leans
into the friend-group angle RomM doesn't emphasize.

muOS first (it has a first-class app-install mechanism and is the easiest target); ROCKNIX is a
later second wrapper around the same binary.

## Goals

- On-device, **controller-driven browse-and-pick** of a birdROMs library.
- **Playlists** — owner-curated collections a friend can grab as a set or cherry-pick from.
- Downloads land in the **correct per-system `roms/` folders**, ready to appear in the game list.
- **Keyboard-less pairing** (the device has no keyboard and no camera).
- **Visual parity with the birdROMs web UI** — retro/arcade dark theme, neon/CRT accents,
  cover-art-forward, Chakra Petch typography. It should read as the same product.
- **One binary across H700 devices** (RG40XX-V, RG35XX+); muOS first.

## Non-goals (explicitly skipped — RomM's turf)

- In-browser/on-device **play**, **save/state sync**, **achievements**, **ROM patching**.
- ROCKNIX and other firmwares in **v1** (muOS only first; architecture keeps ROCKNIX cheap later).
- Uploading from the device (download/consume only).

## Anti-goals (failure even if it "works")

- A client that needs **SSH or a keyboard** to set up.
- **Per-firmware runtime dependency hell** (hence a single static binary).
- Downloads that land in the **wrong folder** or don't show up in the muOS game list.

## Constraints

- **muOS (latest)** on Anbernic **H700** handhelds (RG40XX-V primary; RG35XX+). ARM64, gamepad
  input, small screen, limited RAM/CPU. Exact resolution/layout verified on-device.
- Flaky-wifi tolerant; resumable downloads preferred.
- birdROMs API is token-auth REST; cover art already served at `/api/roms/{id}/cover/`.
- Distributed as a single artifact the user drops on the SD card.

## Decisions (the how — my calls unless marked otherwise)

### 1. Language & UI — Go + SDL2, one static ARM64 binary
Matches the proven prior art (RomM's **Grout** is a single Go binary across ~18 firmwares) and
avoids Python/runtime fragility. SDL2 for a fullscreen, gamepad-navigated UI. **Bundle a TTF
(Chakra Petch)** and the web UI's **color tokens** so the look matches the web app.

### 2. Packaging — muOS `.muxzip` "application"
Ship a `.muxzip` whose `application/` folder carries the binary + a launch script; it appears in
the muOS **Apps** menu. Verify the archive/app spec against the installed muOS version at build time.

### 3. Pairing / auth — camera-less, keyboard-less (v1)
The device has no camera (can't scan a QR) and painful text entry, so **the device displays a
QR + short code**; the friend opens it on their **phone** (already signed into birdROMs),
**approves the device**, and the device **polls** until the server hands it a scoped, revocable
**device token** stored on the card. New birdROMs endpoints:
`POST /api/devices/pair/start` → `{code, qr_url}`; `POST /api/devices/pair/approve` (authed, from
the phone); `GET /api/devices/pair/poll?code=…` → device token once approved.

### 4. Browse model
Top-level sections: **Playlists** and **Platforms**. Platform → cover-art grid of ROM cards
(cover, title, size). Select → queue download. A **download manager** view shows per-item
progress; failures are retryable and don't abort the batch. On-screen text search is secondary
(text entry is painful); browse-by-platform/playlist is primary.

### 5. Folder mapping
Maintain a **platform → muOS `roms/<system>` folder** map (seeded from Grout's known maps,
verified on-device). After a download, trigger whatever muOS needs to **refresh its game list**
so the ROM shows up without a reboot.

### 6. Playlists (birdROMs server feature)
New **Playlist** model: a named, ordered set of ROMs that **any authenticated user can create**.
API to list playlists and their items. In the client a playlist can be grabbed whole or picked from.

### 7. Visual parity
Reuse the web UI's palette tokens + Chakra Petch; dark background, neon accents, cover-art-forward
cards, consistent with the retro/arcade redesign.

## The two pieces of work

**A. birdROMs server additions** (small, in the existing repo):
- Device pairing endpoints + a revocable `DeviceToken` model.
- `Playlist` model + owner CRUD + read API.
- A device-friendly listing API: platforms, ROMs (paginated, with cover URL, size, platform
  folder hint), playlists. (Cover endpoint already exists.)

**B. The client** (new, likely its own repo):
- Go + SDL2 binary, on-card config/token store, pairing flow, browse UI, download manager,
  muOS `.muxzip` packaging.

## Permissions (for now)

Open-by-default for a trusted friend group: **any authenticated user can upload ROMs and create
playlists**. Proper **RBAC is deferred** to a later round. This loosens the current backend
(where upload is restricted to `super_admin`) — a small server change to relax the upload and
playlist-create permissions to any authenticated user. The handheld client is download-only, so
this mainly affects the web/server side.

## Development & testing (SSH/SFTP)

The target devices have **SSH and SFTP enabled**, so the build loop does not depend on manual SD
swaps. Each iteration: push the build to the device over SFTP, SSH in to run it, inspect the real
`roms/<system>` folder names, confirm the muOS app/`.muxzip` conventions, and read logs — on the
actual RG40XX-V (muOS) and RG35XX+. This lets us **verify the firmware specifics empirically**
instead of guessing, de-risking the fiddliest parts (folder mapping, game-list refresh,
packaging). Requires the device's LAN IP + SSH access (key or password) configured once.

## Left to the builder

- Go SDL approach (raw SDL2 bindings vs a helper lib) and input mapping.
- Exact resolution/layout per device (verify on RG40XX-V and RG35XX+).
- Resumable/parallel download details and on-card cover-art caching.
- The precise platform→muOS-folder map (seed from Grout, verify on-device).
- The muOS game-list refresh mechanism after a download.

## Resolved decisions

1. **Pairing:** **QR / phone-approve pairing is in v1.** The device shows a QR + short code, the
   friend scans it with their phone and approves in the birdROMs web UI, and the device polls
   until it receives its scoped, revocable device token (a typed short-code entry is a cheap
   fallback). No paste-token stopgap. *(maintainer)*
2. **Playlists:** **any authenticated user** can create them. *(maintainer)*
3. **Client repo:** a **separate repo** — created: `github.com/amtypaldos/birdroms-handheld` (private). *(maintainer)*
4. **v1 UI scope:** a **pairing screen** (QR + short code + polling) on first run, then the core
   loop — browse **Platforms** + **Playlists** → **download queue**. No per-ROM detail or
   delete/free-space screens in v1. *(my call)*
5. **Permissions:** open for now — any authenticated user uploads and creates playlists; RBAC
   later. *(maintainer)*
