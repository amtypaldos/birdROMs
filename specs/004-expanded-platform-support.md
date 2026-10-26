# 004 — Expanded platform & file-type support

## Status: COMPLETE
Priority: 4

## Problem / Context
`EXTENSION_TO_PLATFORM` in `backend/apps/roms/services.py` only covers a handful of systems.
The library should recognize a broad range of retro platforms (SNES, N64, and many more) so
uploads are classified correctly. This map also feeds the upload allowlist (spec 007), so it
needs to be comprehensive first.

## Acceptance Criteria
- The extension→platform map is expanded to cover the major systems and their common ROM
  extensions, including at least:
  - Nintendo: NES (`.nes`), SNES (`.sfc`/`.smc`), N64 (`.n64`/`.z64`/`.v64`), GameCube
    (`.gcm`/`.rvz`/`.gcz`), Wii (`.wbfs`), Game Boy/Color (`.gb`/`.gbc`), GBA (`.gba`),
    DS (`.nds`), 3DS (`.3ds`/`.cia`).
  - Sega: Master System (`.sms`), Genesis/Mega Drive (`.gen`/`.md`/`.smd`), Game Gear (`.gg`),
    32X (`.32x`), Saturn & Dreamcast disc images (`.chd`/`.gdi`/`.cdi`).
  - Sony: PlayStation (`.pbp`/`.chd`), PS2 (`.iso`/`.chd`), PSP (`.cso`/`.iso`).
  - Others: PC Engine/TurboGrafx (`.pce`), Neo Geo Pocket (`.ngp`/`.ngc`), WonderSwan
    (`.ws`/`.wsc`), Atari 2600/7800/Lynx (`.a26`/`.a78`/`.lnx`), Atari Jaguar (`.jag`/`.j64`).
  - Archives: `.zip`/`.7z` classified as "Archive".
- Genuinely ambiguous extensions (`.iso`, `.bin`, `.cue`, `.chd`, `.zip`) map to a sensible
  generic label ("Disc Image" / "Archive") and remain **manually overridable** via the writable
  `platform` field (today `platform` is only auto-set when left blank — preserve that).
- A single canonical source of supported platforms exists (the map / a derived constant) that
  later specs (allowlist, platform filter) can reuse. The full list is documented in the README.
- Classification is case-insensitive and handles multi-dot filenames.

## Completion Signal
Implementation:
- [x] Expanded, documented extension→platform map.
- [x] Ambiguous extensions handled + manual override preserved.
- [x] README lists supported platforms.

Testing:
- [x] Backend tests classify a representative sample across systems, including ambiguous ones.
- [x] `uv run python manage.py test` passes.

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 1 -->
