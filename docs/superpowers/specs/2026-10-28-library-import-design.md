# Design: import an existing on-disk ROM library

Date: 2026-10-28. Status: approved by the user, 2026-10-28. Repo: `birdROMs` (server). One handheld follow-up is noted at the end and belongs to a separate project.

## Intent and why

The user already has a large, curated ROM library, laid out exactly like a muOS SD card (`ROMS/<SYSTEM>/<game file>`, with `Imgs/<game>.png` box art in most system folders). Today birdROMs only knows ROMs that were uploaded one by one through the web UI, so that library is invisible to it. The user wants birdROMs to **use the library where it already lives**: scan it in place, show every game, scrape what's missing, and keep up with changes, so friends can browse and download the whole collection (web and handheld) without anyone re-uploading 20,000 files.

In production the library lives on a NAS, the NFS share `192.168.2.2:/mnt/volume1/retro-games/roms`, mounted into the birdROMs container on the `docker-apps` host. Deployment (docker-compose on `docker-apps`, behind the reverse proxy on `docker-critical`, which also has a script for adding a site and its DNS) comes after this feature is solid. It is **not** part of this project.

The test library is the user's SD card (`/Volumes/ROMS-RG35/ROMS`, exFAT): about 44 GB, roughly 20,000 files in total, 55 system folders of which about 40 are non-empty. Of those files, **5,535 are game files directly in a system folder** (outside `APPS`/`PORTS`); the rest are box art, ports and app data. 37 folders have an `Imgs/` folder with one PNG per game, and **only 12 games have no `Imgs` PNG**. Most games are a single file (`.chd`, `.PBP`, `.iso`, `.zip`, `.sfc`, `.gba`, …). Arcade folders (`MAME`, `FBNEO`, `NEOGEO`, `CPS1/2/3`, …) use short zip names (`mslug.zip`). `APPS` and `PORTS` hold apps and PC ports, not ROMs. `DREAMCAST` has one game as a folder (`Sonic Adventure/`).

## Goals

1. **Library = single source of truth (user).** A configured library root holding a muOS-style tree. birdROMs reads games from there in place: no copying, moving or renaming of ROM files.
2. **Scan (user).** A full scan adds every game found. Each game gets a platform, a clean title and tags (the existing `parse_rom_filename`, item B), its original file name (= the name on disk), and a cover.
3. **Keep up with changes (user).** A recurring background check picks up added, changed and removed files without the user doing anything. NFS can't notify the app of changes, so this is polling.
4. **Platform from the folder name, including every known alias (user).** `SFC`, `snes`, `SNES`, `snes9x`, … are all SNES; `MD`, `genesis`, `megadrive`, … are all Genesis. Use the alias table in `docs/superpowers/specs/assets/2026-10-28-platform-aliases.csv` (138 platforms, built from muOS's own `core.json` plus Batocera, Knulli, ROCKNIX, AmberELEC, ArkOS, Onion, SpruceOS, MinUI/NextUI and libretro; sources and conflicts are in the `-notes.md` next to it). Every folder on the test card maps to a row.
5. **Covers (user).** Use `Imgs/<game file stem>.png` from the library when present. When a game has none, scrape one (the existing cover pipeline) and **write it into the library** as `ROMS/<SYSTEM>/Imgs/<game file stem>.png`, so the library itself becomes complete.
6. **Uploads land in the library (user).** A web upload is written into the library under the muOS folder of its platform (`ROMS/<muos_folder>/<original filename>`) and then behaves like any scanned game.
7. **Docker default path (user).** The container has one fixed default library path, so a compose file only has to mount the share there.
8. **S3 stays supported (user).** Other deployments can keep their library in an S3-compatible bucket instead of a folder (AWS S3, MinIO, Cloudflare R2, Backblaze B2, via the existing django-storages S3 settings). The user's own deployment uses the NAS folder.

## Non-goals

- Deployment / compose changes for `docker-apps` (later, once this is solid).
- Games made of several files inside their own folder (Dreamcast `Sonic Adventure/`, multi-track `.gdi`/`.cue` sets in folders, `PORTS/*`). v1 treats each file in a system folder as one game; subfolders other than `Imgs` are skipped (and counted in the scan report).
- Real arcade titles for short zip names (`mslug.zip` → "Metal Slug"). v1 uses the file name as the title (as the parser does today); a name lookup from a MAME/FBNeo DAT is a follow-up.
- Save files and save states (Syncthing handles those).
- RBAC (still deferred).
- Content hashing / duplicate detection across folders. If `SFC/` and `snes/` both contain the same game, both are listed.

## Anti-goals (failure even if it "works")

- **Deleting, moving or renaming anything in the library.** The only writes birdROMs ever makes to the library are (a) new upload files and (b) new `Imgs/*.png` covers for games that have none. It never overwrites an existing file in either case.
- **Mass "removal" when the share is unavailable.** If the NFS mount is down or the root looks empty or unreadable, a scan must not mark the whole library as gone, drop games from playlists or lose metadata. See "Missing files".
- **Re-reading 44 GB on every check.** Change detection must not hash or read whole files (or download S3 objects). It uses size and modified time (S3: size and LastModified/ETag).
- **Breaking the handheld's download folders.** The platform name stored for a game must map back to the right muOS folder on the handheld, and the original file name keeps working for saves.

## Constraints

- Existing stack: Django 5 + DRF, Postgres, Huey (immediate in dev, Redis worker in prod; `birdroms/tasks.py` already has periodic tasks), storage via `birdroms/storage.py`. `uv` for Python. Local dev uses native Postgres and no Docker.
- The library root may be a slow network mount or a remote bucket. Scans must be incremental (batch DB writes, no per-file queries in hot loops) and must tolerate odd names (Unicode, brackets, commas, `'`). Use exact whole-folder-name matching only for aliases: short aliases like `64`, `tg`, `pc`, `ng` are risky.
- Ignore hidden files, macOS litter (`._*`, `.DS_Store`, `.Spotlight-V100`, `.fseventsd`, `.Trashes`), `Imgs/` (it's art) and non-game folders (`kind=non-game` in the alias table: `APPS`, `PORTS`).
- `NGP` holds both Neo Geo Pocket and Color, and `WS` holds both WonderSwan and Color: split by extension within the folder. `pico` means PICO-8 (muOS/Onion meaning).
- **Testing:** do not write to the SD card from the Mac (macOS creates `._*` litter on exFAT). Tests that write (covers, uploads) use a temporary copy or a local library folder. Read-only scans may point at `/Volumes/ROMS-RG35/ROMS`; the user may also copy the library to the Mac.

## Decided by the user

Single source of truth. In-place reading. S3 stays supported for other deployments. muOS layout. Scan, scrape and recurring change check. A fixed default path in the container. Uploads written into the library. Platform from the folder via every known alias. Scraped covers written to the NAS `Imgs/`. Production library on the NFS share above.

## My calls (the builder can rely on these; the user can still change them)

1. **One library root, configured by env** (e.g. `LIBRARY_ROOT`, default `/library` in the container). The scanner looks for the systems folder as `ROMS/` or `Roms/` directly under the root, or treats the root itself as the systems folder if it has none. The Mac dev value points at a local copy.
2. **ROM identity = its path relative to the library root.** That path is unique per ROM. Size and mtime are stored for change detection. A changed size or mtime means "file changed": refresh the stored size, keep the ROM row, its title edits and playlist membership.
3. **Missing files.** A file that's gone is **flagged missing, not deleted**. It's hidden from listings and downloads, and keeps its playlist entries and metadata. If it comes back at the same path, it's un-flagged. **Safety guard:** a scan aborts without flagging anything if the root is unreachable or has no systems folder, or if it would flag more than a set share of the library missing in one pass (e.g. 25%; configurable). The guard is logged and visible in the scan status.
4. **Schedule.** A periodic change check every 15 minutes by default (env-overridable crontab, like `COVER_ART_SWEEP_CRONTAB`), plus a manual "Rescan now" for admins. Only one scan runs at a time.
5. **Visibility.** A small admin-visible scan status: last scan time, games added/changed/missing/skipped, and the reason for any abort. Show it in the web UI wherever admin tools already live, or as a compact panel. Plus a management command (`manage.py scan_library`) for the first big import and for scripting.
6. **Platform names.** Store the alias table's `canonical_platform`. Keep the 22 platform names the handheld already uses ("SNES", "Sega Genesis", "Game Boy Advance", …) exactly as they are, so existing downloads still map to the same folders. The alias table follows them where they overlap.
7. **Uploads.** Platform from the upload (as today, user-overridable). The file is written to `ROMS/<muos_folder>/<original filename>`. If that file already exists, the upload is refused with a clear message, never overwritten. Platforms with no muOS folder go to `ROMS/_UNSORTED/`, matching the handheld's fallback.
8. **Cover precedence.** Library `Imgs/<stem>.png` first, then an already-stored scraped cover, then scrape. A scraped cover is written to `Imgs/<stem>.png` as PNG (converted if the source is JPEG) only if that file doesn't exist. Covers continue to be served through the existing authenticated cover endpoint.
9. **Library backends: folder or S3, same layout.** `LIBRARY_BACKEND=filesystem` (default; `LIBRARY_ROOT` is a path) or `s3` (a bucket plus an optional prefix, reusing the existing `S3_*` settings). Both use the same muOS layout (`ROMS/<SYSTEM>/<game>`, `ROMS/<SYSTEM>/Imgs/<stem>.png`) and behave the same. An S3 library is scanned by listing objects (`ListObjectsV2`, paginated). Its change detection uses each object's size and `LastModified` (or ETag) in place of mtime, and it never downloads objects to scan. Uploads and scraped covers are written as new objects, never overwriting existing keys. Downloads keep streaming through the authenticated endpoint. The "unreachable" safety guard covers S3 errors (credentials, missing bucket) as well as a down mount. App-owned files (cached covers, anything not in the library) stay in the existing media storage, whichever backend the library uses. The 3 existing dev ROMs are re-imported from the library instead of being migrated.
10. **Arcade folders and odd systems** (`MAME`, `FBNEO`, `HBMAME`, `NAOMI`, `ATOMISWAVE`, `CPS*`, `NEOGEO`, `PGM2`, `VARCADE`, `GW`, `POKE`, `PICO`, `ONS`, `EASYRPG`, `OPENBOR`, …) are imported like any other system, with their canonical platform from the table and the file name as the title.
20. **Scraping and cover write-back on the first import are automatic.** Games without art go through the existing throttled cover queue (`scrape_rom_cover` and the hourly sweep), and new covers are written to `Imgs/` as they arrive. On the test library that's about 12 games. A setting (e.g. `LIBRARY_WRITE_COVERS`, default on) turns library write-back off; covers then stay in media storage only. ScreenScraper quotas are handled the way the existing pipeline already does.

12. **What counts as a game.** A file directly in a system folder whose extension (case-insensitive) is a known single-file ROM/disc format: the existing `SUPPORTED_EXTENSIONS` plus the formats the card actually uses (`.chd`, `.pbp`, `.iso`, `.cso`, `.zip`, `.7z`, `.rom`, `.mgw`, `.p8`/`.png` for PICO-8 carts, …; the builder derives the final list from the card and the alias table's platforms). Multi-file sets (`.cue` + `.bin`, `.gdi` + tracks, `.m3u` playlists and the discs they list) are skipped in v1 and counted as "skipped (multi-file)" in the scan report. Other files (`.txt`, `.xml`, `.dat`, `.srm`, `.sbi`, …) are ignored without being counted as errors.
13. **When the library isn't writable** (read-only mount, root-squash, wrong UID, or S3 credentials without write permission): an upload fails with a clear error and nothing is stored elsewhere. A scraped cover is still kept in birdROMs' own media storage and served from there, and the scan status shows that covers couldn't be written to the library. A read-only library is a supported setup: browse and download work, and uploads and cover write-back are disabled with a visible note.
14. **Missing-file guard details.** The guard compares against the library's size before this scan, over the whole library, and only applies when the library had at least 50 games. Admins can accept a big removal explicitly: `scan_library --accept-removals` and an "Accept removals" action next to the aborted status. A first scan (empty DB) never trips it.
15. **Missing games in playlists.** Playlist detail and list responses omit missing ROMs from `roms` and from `rom_count`. The entries stay in the database and reappear if the file returns. `rom_ids` writes reject missing ROMs. This means the handheld never queues a download that would fail.
16. **Who "uploaded" a library game.** `uploaded_by` becomes optional (set null on user delete) and a `source` field records `library` vs `upload`. Scanned games have no uploader, and the API shows none. "Newest first" ordering uses the time birdROMs first saw the file, not the file's mtime.
17. **Unknown folders** (not in the alias table): skipped and listed by name in the scan report, so a new firmware's folder name is easy to add. No platform is invented for them.
18. **One scan at a time** across the web process and the worker: a database lock (advisory lock or status-row lock). "Rescan now" enqueues a scan and never runs inline. A periodic tick that finds a scan running is skipped.
19. **Renames and moves** are a new game plus a missing one. Playlist entries and title edits don't follow the file. This is accepted for v1.

11. **The handheld's folder map** (`birdroms-handheld/internal/platforms`) is regenerated from the same alias table, so every platform the server can produce has a download folder. This is a small change in the other repo, but it's part of this project because the server now produces many more platform names.

## Left to the builder

The exact model fields and migrations (e.g. `path`, `size_bytes`, `mtime`, `missing`, `source`). How `ROM.file` relates to the library (a Django storage pointed at the library root — `FileSystemStorage(location=LIBRARY_ROOT)` or an S3 storage with the library prefix — or a path field read directly), whichever keeps downloads streaming and permission-checked for both backends. The scanner's listing abstraction over the two backends. How S3 tests run without a real bucket (e.g. moto or a stubbed client). Batching and performance details. The scan-status model and UI placement. How the alias CSV ships (data file vs generated Python). Logging. The exact abort threshold. How to test scanning without the real card (fixture trees in temp dirs).

## Follow-ups (separate projects, recorded so they aren't lost)

- **Handheld writes box art into muOS** when it downloads a game: save the game's cover (library `Imgs` or scraped) into muOS's per-system box-art folder under `MUOS/info/catalogue/`, so muOS's own game list shows art. Confirm the exact path and naming on the device. Part of the "super easy handheld install" project.
- **Super easy handheld install** and docs (next project).
- **README and docs cleanup** after both.
- Arcade title lookup from a DAT; multi-file / folder games; docker-compose deployment on `docker-apps`.
