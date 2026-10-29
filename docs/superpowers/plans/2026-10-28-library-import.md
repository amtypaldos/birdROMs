# Library Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** birdROMs scans an existing muOS-layout ROM library (a folder, e.g. the NAS share, or an S3 bucket) in place, keeps up with changes, links or scrapes covers into the library, and writes web uploads into it.

**Architecture:** A `Library` abstraction (filesystem or S3) lists `ROMS/<SYSTEM>/<file>` and `ROMS/<SYSTEM>/Imgs/<png>` with size + modified time. A scanner diffs that listing against `ROM` rows (identity = `ROM.file.name`, the path relative to the library root) and adds, updates, flags missing, or restores games, behind a missing-file guard and a database lock. `ROM.file` uses a storage rooted at the library, so downloads keep streaming through the authenticated endpoint. Platforms come from a shared folder-alias table, also embedded in the handheld.

**Tech Stack:** Django 5 + DRF, PostgreSQL, Huey, django-storages (S3), Pillow (new), React 18 + Vite + vitest; Go (handheld).

**Spec:** `docs/superpowers/specs/2026-10-28-library-import-design.md` (with `assets/2026-10-28-platform-aliases.csv` and `-notes.md`).

## Global Constraints

- The library is the single source of truth. birdROMs never deletes, moves, renames or overwrites anything in it. Its only writes are new upload files and new `Imgs/<stem>.png` covers for games that have none.
- Library backends: `LIBRARY_BACKEND=filesystem` (default; `LIBRARY_ROOT`, default `/library`) or `s3` (existing `S3_*` settings + `LIBRARY_S3_PREFIX`, default `""`). Same layout, same behaviour.
- Env settings (exact names and defaults): `LIBRARY_BACKEND=filesystem`, `LIBRARY_ROOT=/library`, `LIBRARY_S3_PREFIX=`, `LIBRARY_READ_ONLY=false`, `LIBRARY_WRITE_COVERS=true`, `LIBRARY_SCAN_CRONTAB=*/15 * * * *`, `LIBRARY_MISSING_GUARD_RATIO=0.25`, `LIBRARY_MISSING_GUARD_MIN=50`.
- Systems folder: `ROMS/` or `Roms/` directly under the root (first that exists), else the root itself.
- Platform from the folder name via the alias table, exact whole-name, case-insensitive match. `kind=non-game` folders (`APPS`, `PORTS`), `Imgs`, hidden files and macOS litter (`._*`, `.DS_Store`, `.Spotlight-V100`, `.fseventsd`, `.Trashes`) are ignored. Unknown folders are skipped and listed by name in the scan report.
- `NGP` → "Neo Geo Pocket", except `.ngc` files → "Neo Geo Pocket Color". `WS` → "WonderSwan", except `.wsc` → "WonderSwan Color".
- Change detection uses size + modified time only (S3: size + LastModified). It never reads or hashes file contents.
- Missing files are flagged (`missing=True`), never deleted. Guard: when the library had ≥ `LIBRARY_MISSING_GUARD_MIN` present games before the scan and the scan would flag more than `LIBRARY_MISSING_GUARD_RATIO` of them missing, abort without changes unless `accept_removals=True`. An unreachable root or absent systems folder also aborts without changes.
- One scan at a time across processes (Postgres advisory lock). "Rescan now" enqueues a scan and never runs it inline.
- Covers: `Imgs/<stem>.png` first, then the stored scraped cover, then scrape. A scraped cover is written to `Imgs/<stem>.png` (PNG) only if absent and only when `LIBRARY_WRITE_COVERS` is on and the library is writable.
- Uploads: written to `<systems>/<muos_folder>/<original filename>` (`_UNSORTED` when the platform has no muOS folder). If the file exists, they're refused and never overwritten. If the library is read-only, they're refused with a clear message.
- The 22 platform names the handheld already uses stay exactly as they are (all are canonical names in the alias table).
- TDD (failing test first). Backend tests: `cd backend && uv run python manage.py test`. Frontend: `cd frontend && PATH="$HOME/.local/share/mise/shims:$PATH" yarn test` / `yarn lint` / `yarn build`. Handheld: `just test`, `go vet ./...`. Commit messages use conventional prefixes and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never write to the user's SD card (`/Volumes/ROMS-RG35`) from the Mac (macOS `._*` litter). Tests use temporary directory trees.

## Review Focus

1. **NAS share down or empty during a scheduled scan.** Nothing is flagged missing, playlists are untouched, and the status says why (Task 4 tests `test_unreachable_root_aborts_without_changes`, `test_empty_systems_folder_aborts_without_changes`).
2. **Real-world names:** apostrophes, commas, brackets, accents (`Pokémon`), `&`, and very long names are stored, listed and downloaded under the exact on-disk name (Task 4 `test_odd_names_round_trip`, Task 6 `test_download_uses_exact_library_name`).
3. **Alias twins on one card** (`SFC/` and `snes/` both holding the same game): both are listed, with the same platform (Task 4 `test_alias_folders_share_platform`).
4. **Case and layout variants:** `ROMS` vs `Roms` vs root-as-systems-folder, `.PBP`/`.PNG` upper-case extensions, `imgs` vs `Imgs` (Task 2 `test_systems_folder_detection`, Task 4 `test_uppercase_extensions_and_cover_match`).
5. **An upload whose file already exists, or a read-only library:** clear refusal, nothing overwritten, no orphan DB row (Task 6 `test_upload_refuses_existing_file`, `test_upload_refused_when_read_only`).

---

### Task 1: Platform alias table and lookup

**Files:**
- Create: `backend/apps/roms/data/platform_aliases.csv` (copy of `docs/superpowers/specs/assets/2026-10-28-platform-aliases.csv`)
- Create: `backend/apps/roms/platform_aliases.py`
- Test: `backend/apps/roms/test_platform_aliases.py`

**Interfaces:**
- Produces: `PlatformInfo(name: str, muos_folder: str, kind: str)` (frozen dataclass; `kind` in `game|arcade|non-game`); `platform_for_folder(folder: str) -> PlatformInfo | None`; `platform_for_game(folder: str, filename: str) -> PlatformInfo | None` (applies the NGP/WS extension split, returns None for non-game folders); `muos_folder_for(platform: str) -> str | None`; `UNSORTED_FOLDER = "_UNSORTED"`. The CSV is loaded once (module-level cache).

- [ ] **Step 1: Write failing tests**: `platform_for_folder("SFC").name == "SNES"`, likewise for `"snes"` and `"SNES"`; `platform_for_folder("megadrive").name == "Sega Genesis"`; `platform_for_folder("MDCD").name == "Sega CD / Mega-CD"`; `platform_for_folder("PICO").name == "PICO-8"`; `platform_for_folder("PORTS").kind == "non-game"`; `platform_for_folder("nope") is None`; `platform_for_folder("64") is None` unless the CSV lists it as an exact alias (assert whichever the CSV says, via a lookup in the test); `platform_for_game("NGP", "x.ngc").name == "Neo Geo Pocket Color"`; `platform_for_game("NGP", "x.ngp").name == "Neo Geo Pocket"`; `platform_for_game("WS", "x.wsc").name == "WonderSwan Color"`; `platform_for_game("APPS", "a.sh") is None`; `muos_folder_for("SNES") == "SFC"`; `muos_folder_for("Sega Genesis") == "MD"`; `muos_folder_for("unknown-thing") is None`. Plus `test_handheld_names_are_canonical`: each of the 22 names (NES, SNES, Nintendo 64, Game Boy, Game Boy Color, Game Boy Advance, Nintendo DS, Sega Master System, Sega Genesis, Sega Game Gear, Sega 32X, Sega Dreamcast, Sony PlayStation, Sony PSP, PC Engine / TurboGrafx-16, Neo Geo Pocket, Neo Geo Pocket Color, WonderSwan, WonderSwan Color, Atari 2600, Atari 7800, Atari Lynx) has a non-empty `muos_folder_for`.
- [ ] **Step 2:** Run `uv run python manage.py test apps.roms.test_platform_aliases`. Expected: ImportError.
- [ ] **Step 3:** Implement with `csv.DictReader` over the packaged CSV (`aliases` is `;`-separated and lower case; match on `folder.strip().lower()`).
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: platform folder-alias table and lookup`.

### Task 2: Library settings and backends

**Files:**
- Create: `backend/birdroms/library_config.py` (env parsing, mirrors `storage.py` / `deploy_config.py` style)
- Create: `backend/apps/roms/library.py`
- Modify: `backend/birdroms/settings.py` (expose `LIBRARY = parse_library_settings(os.environ)`; under `TESTING`, a temp library root like the existing temp `MEDIA_ROOT`)
- Test: `backend/apps/roms/test_library.py`

**Interfaces:**
- Produces: `LibrarySettings` (frozen dataclass: `backend: str`, `root: str`, `s3_prefix: str`, `read_only: bool`, `write_covers: bool`, `scan_crontab: str`, `guard_ratio: float`, `guard_min: int`); `parse_library_settings(env) -> LibrarySettings` (raises `ValueError` for an unknown backend); `LibraryEntry(path: str, size: int, modified: datetime)` (path is `/`-separated, relative to the library root; `modified` is timezone-aware UTC); `class LibraryUnavailable(Exception)`; abstract `Library` with `systems_prefix: str` (`"ROMS"`, `"Roms"` or `""`), `writable: bool`, `storage` (a Django `Storage` rooted at the library root), `entries() -> Iterator[LibraryEntry]` (only `<systems>/<SYS>/<file>` and `<systems>/<SYS>/<Imgs>/<file>` for any-case `imgs`; raises `LibraryUnavailable` when the root or systems folder can't be listed), `exists(path: str) -> bool`, `write_new(path: str, data: bytes) -> None` (raises `FileExistsError` if present, `PermissionError` if not writable); `FilesystemLibrary(root: str, read_only: bool)`; `S3Library(storage: S3Storage, prefix: str, read_only: bool)` (lists with `storage.bucket.objects.filter(Prefix=...)`, using each object's `key`, `size` and `last_modified`); `get_library() -> Library`; `library_storage() -> Storage` (callable for `FileField(storage=...)`).

- [ ] **Step 1: Write failing tests:**
  - `parse_library_settings({})` equals the defaults in Global Constraints. A bad backend raises `ValueError`.
  - `test_systems_folder_detection`: temp roots with `ROMS/`, with `Roms/`, and with system folders directly at the root give `systems_prefix` `"ROMS"`, `"Roms"` and `""`.
  - `entries()` returns files and `Imgs` PNGs with sizes and UTC mtimes, skips deeper subfolders and hidden/`._` files, and raises `LibraryUnavailable` for a missing root.
  - `write_new` creates parent folders, refuses an existing file (`FileExistsError`) and refuses on `read_only` (`PermissionError`). `writable` is False when the root isn't writable (`os.access`).
  - The S3 tests use a fake bucket object exposing `objects.filter(Prefix=...)`, returning objects with `key`, `size` and `last_modified`, and a fake storage for `exists`/`save`. They check the prefix is stripped from paths and that `write_new` refuses existing keys.
- [ ] **Step 2:** Run `uv run python manage.py test apps.roms.test_library`. Expected: ImportError.
- [ ] **Step 3:** Implement. The filesystem listing uses `os.scandir` with one `stat` per entry. The S3 storage is built from the existing `_s3_options` with `location=prefix` (`file_overwrite=False`).
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: library settings and folder/S3 library backends`.

### Task 3: Model changes

**Files:**
- Modify: `backend/apps/roms/models.py`
- Create: migration `0007_library_import.py` (via `makemigrations --name library_import`)
- Test: `backend/apps/roms/test_library_models.py`

**Interfaces:**
- Consumes: `library_storage` (Task 2).
- Produces on `ROM`:
  - `file = FileField(storage=library_storage, max_length=1024, unique=True, upload_to=<identity function keeping the given name>)`; `file.name` is the library-relative path.
  - `size_bytes = BigIntegerField(null=True, blank=True)`, `modified_at = DateTimeField(null=True, blank=True)`.
  - `missing = BooleanField(default=False, db_index=True)`.
  - `source = CharField(max_length=10, choices=[("upload","Upload"),("library","Library")], default="upload")`.
  - `cover_path = CharField(max_length=1024, blank=True, default="")` (library-relative path of the cover PNG).
  - `uploaded_by` becomes `null=True, blank=True, on_delete=SET_NULL`.
- Produces a new model `LibraryScan`:
  - `started_at` (auto_now_add), `finished_at` (null), `state` (`running|ok|aborted|failed`).
  - Counters (PositiveIntegerField, default 0): `added`, `changed`, `missing`, `restored`, `skipped_multifile`, `skipped_other`.
  - `unknown_folders = JSONField(default=list)`, `message = TextField(blank=True)`, `accept_removals = BooleanField(default=False)`.
  - Meta ordering `["-started_at", "-id"]`.

- [ ] **Step 1: Write failing tests:**
  - A ROM created with `file.name = "ROMS/SFC/Game (USA).smc"` keeps that exact name.
  - Two ROMs with the same file name violate the unique constraint (`IntegrityError`).
  - `uploaded_by=None` saves, and deleting a user sets it to null.
  - `LibraryScan.objects.first()` is the newest scan.
- [ ] **Step 2:** Run. Expected: failures.
- [ ] **Step 3:** Implement and run `makemigrations --name library_import`. Existing tests that create ROMs through uploads must still pass (they now write into the temp test library). Fix only test helpers that hard-coded `roms/` storage paths.
- [ ] **Step 4:** Run the full backend suite and `makemigrations --check`. Expected: PASS, no changes.
- [ ] **Step 5: Commit** `feat: ROM library fields and scan history model`.

### Task 4: Scanner core

**Files:**
- Create: `backend/apps/roms/scanner.py`
- Test: `backend/apps/roms/test_scanner.py`

**Interfaces:**
- Consumes: Tasks 1–3; `parse_rom_filename` (`services.py`).
- Produces:
  - `GAME_EXTENSIONS: frozenset[str]`: `SUPPORTED_EXTENSIONS` ∪ `{.zip, .md, .nes, .gb, .smc, .gbc, .sms, .pce, .gg, .rom, .gba, .a26, .mgw, .ws, .ngc, .p8, .chd, .sfc, .wsc, .min, .vb, .pbp, .nds, .iso, .pak, .z64, .v64, .bin, .cso, .ngp, .n64, .7z, .32x, .a52, .a78, .lnx, .fds, .sgx, .col, .adf, .d64, .t64, .prg, .dsk, .st, .msa, .mx1, .mx2}`, lower case.
  - `MULTIFILE_EXTENSIONS = {.cue, .gdi, .m3u, .ccd, .mds}`. In a system folder containing any of these, `.bin`, `.img`, `.raw` and `.sub` files also count as multi-file parts.
  - `ScanResult` (dataclass: `added`, `changed`, `missing`, `restored`, `skipped_multifile`, `skipped_other: int`, `unknown_folders: list[str]`, `aborted_reason: str = ""`, `added_ids: list[int]`).
  - `scan_library(library: Library, *, accept_removals: bool = False, guard_ratio: float, guard_min: int) -> ScanResult`. No locking, no task enqueueing, no `LibraryScan` rows.

- [ ] **Step 1: Write failing tests** (build temp trees with a `FilesystemLibrary`):
  - `test_first_scan_adds_games`: `ROMS/SFC/Super Mario World (U).smc` + `ROMS/SFC/Imgs/Super Mario World (U).png` + `ROMS/MD/Sonic.md`. The result has `added == 2`. The SMW row has platform `"SNES"`, title `"Super Mario World"`, tags `["USA"]`, filename `"Super Mario World (U).smc"`, extension `".smc"`, `source == "library"`, `uploaded_by is None`, the correct `size_bytes`, `modified_at` set, and `cover_path == "ROMS/SFC/Imgs/Super Mario World (U).png"`. Sonic has `cover_path == ""`.
  - `test_rescan_unchanged_is_noop`: a second scan gives all counters 0.
  - `test_changed_file_updates_size_keeps_row`: rewriting the file with new size/mtime gives `changed == 1`, and the same id, edited title and playlist membership are kept.
  - `test_removed_file_flagged_missing_and_restored`: delete the file and it's `missing == 1`, row `missing=True`, the playlist item still in the DB. Recreate it and it's `restored == 1`, `missing=False`.
  - `test_guard_aborts_mass_removal`: 60 games, delete 20 (more than 25%). The scan has `aborted_reason` set and no row changed. The same scan with `accept_removals=True` flags 20.
  - `test_guard_ignored_below_min`: 3 games, delete 2. They're flagged without aborting.
  - `test_unreachable_root_aborts_without_changes` and `test_empty_systems_folder_aborts_without_changes`.
  - `test_unknown_and_non_game_folders`: `ROMS/WEIRD/x.smc` is skipped with `unknown_folders == ["WEIRD"]`. `ROMS/PORTS/a.sh` is ignored and not reported. `ROMS/DREAMCAST/Sonic Adventure/track.bin` (a subfolder) is counted in `skipped_other`.
  - `test_multifile_sets_skipped`: `ROMS/PS/Game.cue` + `ROMS/PS/Game (Track 1).bin` gives `skipped_multifile == 2` and no rows.
  - `test_alias_folders_share_platform`: the same file in `SFC/` and `snes/` gives 2 rows, both platform `"SNES"`.
  - `test_uppercase_extensions_and_cover_match`: `ROMS/PS/Game.PBP` with `ROMS/PS/imgs/Game.PNG` is added with the cover linked.
  - `test_odd_names_round_trip`: files named `Tony Hawk's Underground 2 (USA, Europe).gba`, `Pokémon - Edición Esmeralda (Spain).gba` and `Lilo & Stitch.gba` are added, and `ROM.file.name` and `filename` equal the exact names.
  - `test_cover_appears_later_is_linked`: adding the `Imgs` PNG on a later scan sets `cover_path`, counted as `changed`.
  - `test_ngp_split`: `ROMS/NGP/a.ngc` gives `"Neo Geo Pocket Color"`.
  - `test_ignores_litter`: `._x.smc`, `.DS_Store` and `x.txt` aren't rows. `x.txt` counts in `skipped_other`; litter isn't counted.
- [ ] **Step 2:** Run `uv run python manage.py test apps.roms.test_scanner`. Expected: ImportError.
- [ ] **Step 3:** Implement:
  - Load existing rows once (`values("id","file","size_bytes","modified_at","missing","cover_path")`).
  - Diff by path, then apply with `bulk_create` / `bulk_update` in batches of 500 inside one transaction.
  - Set every field explicitly; `bulk_create` skips `ROM.save`.
- [ ] **Step 4:** Run the tests. Expected: PASS. Then run the full suite.
- [ ] **Step 5: Commit** `feat: scan the library and keep ROM rows in sync`.

### Task 5: Scan runs: lock, record, schedule, command

**Files:**
- Modify: `backend/apps/roms/scanner.py` (add `run_library_scan`)
- Modify: `backend/birdroms/tasks.py` (periodic + on-demand tasks)
- Create: `backend/apps/roms/management/commands/scan_library.py`
- Test: `backend/apps/roms/test_scan_runs.py`

**Interfaces:**
- Consumes: `scan_library`, `get_library`, `settings.LIBRARY`, `scrape_rom_cover`.
- Produces:
  - `run_library_scan(*, accept_removals: bool = False, library: Library | None = None) -> LibraryScan | None`:
    - Takes `pg_try_advisory_lock(<constant key>)` and returns None when it's busy.
    - Writes a `LibraryScan` row (`running`, then `ok`, `aborted` with the reason in `message`, or `failed` with the exception text).
    - After an `ok` scan, enqueues `scrape_rom_cover(id)` for each added ROM with no `cover_path`.
  - Tasks: `scan_library_task(accept_removals: bool = False)` (`@db_task`); `scan_library_periodic()` (`@db_periodic_task(crontab from LIBRARY.scan_crontab)`).
  - `parse_scan_crontab` follows `parse_sweep_crontab`'s style.
  - Command: `manage.py scan_library [--accept-removals]`, which prints the counters, the unknown folders and any abort reason. It exits with status 1 when aborted or failed.

- [ ] **Step 1: Write failing tests:**
  - `run_library_scan` on a temp library records an `ok` scan with counters.
  - An aborted scan is recorded `aborted` with the reason.
  - A second call while the lock is held (hold it via a separate connection, or patch the lock helper) returns None and writes no row.
  - Added ROMs without covers enqueue `scrape_rom_cover` (patch the task) and ROMs with covers don't.
  - The command's output contains `added: N` and it exits non-zero on abort.
  - `parse_scan_crontab({})` is `*/15`.
- [ ] **Step 2:** Run. Expected: failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests and the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: scheduled, locked library scans and a scan_library command`.

### Task 6: API: hide missing games, library-backed uploads, covers, status

**Files:**
- Modify: `backend/apps/roms/views.py`, `serializers.py`, `urls.py`, `permissions.py`, `cover_art.py` (`roms_missing_cover_art` in `tasks.py`)
- Create: `backend/apps/roms/library_views.py`
- Test: `backend/apps/roms/test_library_api.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces:
  - **Hide missing games.** ROM list, `platforms`, the device listing and playlist detail/list (`roms` and `rom_count`) exclude `missing=True`. Download and cover of a missing ROM give 404. `rom_ids` writes reject missing ROMs ("Unknown ROM id(s)" message unchanged).
  - **Device listing sizes.** `DeviceROMSerializer.size_bytes` uses the stored `size_bytes` when not None, else falls back to `file.size`.
  - **Covers.** The cover endpoint serves `cover_path` from the library storage when set, else `cover_art` from media.
  - **Uploads.** `ROMSerializer.create` writes into the library at `<systems_prefix>/<muos_folder or "_UNSORTED">/<cleaned upload name>` through `Library.write_new`. It sets `source="upload"`, `size_bytes` and `modified_at`. When the file exists it raises a 400 `ValidationError` on `file`: `"<name> is already in the library."`. When the library isn't writable: `"Uploads are disabled: the ROM library is read-only."`. No ROM row is created in either case.
  - **Uploader.** `uploaded_by_username` is `null` when `uploaded_by` is null.
  - **Status endpoints** (both: `role == "super_admin"`, else 403):
    - `GET /api/library/status/` → `{"backend": str, "writable": bool, "write_covers": bool, "running": bool, "last_scan": {state, started_at, finished_at, added, changed, missing, restored, skipped_multifile, skipped_other, unknown_folders, message} | null}`.
    - `POST /api/library/scan/` with body `{"accept_removals": bool}` → 202 `{"queued": true}`, or 409 `{"detail": "A library scan is already running."}`.
  - **Cover sweep.** `roms_missing_cover_art()` filters `cover_art="", cover_path="", missing=False`.

- [ ] **Step 1: Write failing tests:**
  - A missing ROM is absent from `/api/roms/`, `/api/roms/?fields=device`, `/api/roms/platforms/` (when it's the platform's only ROM), playlist `roms` and `rom_count`. Its download and cover give 404.
  - `test_download_uses_exact_library_name`: a library ROM named `Tony Hawk's Underground 2 (USA, Europe).gba` streams with that `Content-Disposition` filename.
  - The cover endpoint returns the library PNG bytes for a `cover_path` ROM.
  - An upload of `Super Mario World (U).smc` with platform `SNES` lands at `ROMS/SFC/Super Mario World (U).smc` in the temp library.
  - An upload with platform `Archive` lands in `ROMS/_UNSORTED/`.
  - `test_upload_refuses_existing_file`: 400 with the exact message, the existing bytes unchanged, no new row.
  - `test_upload_refused_when_read_only`: 400 with the exact message.
  - The status and scan endpoints give 403 for readonly users and 202/409 for admins (patch the task enqueue and the running check).
  - Device listing `size_bytes` comes from the stored value without touching storage (patch `file.size` to raise).
- [ ] **Step 2:** Run. Expected: failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite and `makemigrations --check`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: library-backed uploads, missing-game hiding and library status API`.

### Task 7: Scraped covers written into the library

**Files:**
- Modify: `backend/apps/roms/cover_art.py` (`scrape_rom`)
- Modify: `backend/pyproject.toml` (add `pillow`, exact pinned version)
- Test: `backend/apps/roms/test_cover_writeback.py`

**Interfaces:**
- Consumes: `get_library()`, `settings.LIBRARY.write_covers`.
- Produces: after `scrape_rom` saves a new cover (media, as today), a library ROM whose `<dir>/Imgs/<stem>.png` doesn't exist gets that PNG written (converted with Pillow when the source isn't PNG) and `cover_path` set. Skipped silently, keeping the media cover, when write-back is off, the library isn't writable, the PNG already exists, or the write raises.

- [ ] **Step 1: Write failing tests** (mock the provider to return JPEG bytes from a tiny Pillow image):
  - A library ROM without art gets `ROMS/SFC/Imgs/<stem>.png` written, a valid PNG, with `cover_path` set.
  - An existing PNG is not overwritten (its bytes are unchanged) and `cover_path` points at it.
  - With `write_covers=False` nothing is written and the media cover is still saved.
  - On a read-only library nothing is written and there's no exception.
- [ ] **Step 2:** Run. Expected: failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests and the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: write scraped covers into the library's Imgs folder`.

### Task 8: Web UI: library status panel for admins

**Files:**
- Create: `frontend/src/LibraryStatusPanel.jsx`, `frontend/src/LibraryStatusPanel.test.jsx`
- Modify: `frontend/src/api/client.js` (+ `client.test.js`), `frontend/src/App.jsx` (render the panel on the Library view when `me.role === "super_admin"`), `frontend/src/styles.css`

**Interfaces:**
- Consumes: `GET /api/library/status/`, `POST /api/library/scan/` (Task 6).
- Produces: `api.libraryStatus()`, `api.rescanLibrary({ acceptRemovals = false } = {})`.

- [ ] **Step 1: Write failing tests:**
  - The panel shows the last scan's time and counts ("added", "changed", "missing").
  - "Rescan now" posts `{accept_removals: false}` and shows "Scanning…".
  - While `running` it polls `libraryStatus` every 5 s (fake timers) and stops when done.
  - An `aborted` scan shows its message and an "Accept removals" button that posts `{accept_removals: true}`.
  - A 409 shows "A library scan is already running."
  - `writable: false` shows "Read-only library: uploads and cover saving are off."
  - Unknown folders are listed.
  - Non-admins don't see the panel.
  - An upload refusal message from the API is shown in the upload panel (existing error path).
- [ ] **Step 2:** Run `yarn test`. Expected: failures.
- [ ] **Step 3:** Implement; keep it compact, matching existing card styles.
- [ ] **Step 4:** Run `yarn test`, `yarn lint`, `yarn build`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: library scan status and rescan controls for admins`.

### Task 9: Configuration and container defaults

**Files:**
- Modify: `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example` (and `backend/.env.example` if one exists)
- Test: `backend/apps/roms/test_library.py` (extend)

**Interfaces:**
- Produces:
  - Dev compose: the backend and worker mount `${LIBRARY_PATH:-./library}:/library` with `LIBRARY_ROOT: /library`.
  - Prod compose: both share a named volume `birdroms_library` mounted at `/library`. There's a commented NFS example for `192.0.2.10:/srv/roms` (`driver_opts: type: nfs, o: addr=192.0.2.10,rw,nfsvers=4, device: ":/srv/roms"`).
  - `.env.example` documents every `LIBRARY_*` variable with its default and a one-line meaning.

- [ ] **Step 1: Write failing test:** `test_env_example_documents_library_settings`. Every field of `LibrarySettings` has a matching `LIBRARY_*` line in the repo's `.env.example`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Edit the files. `docker compose config` must succeed if Docker is available; otherwise check the YAML with `python -c "import yaml"` if PyYAML is present. Note which check ran.
- [ ] **Step 4:** Run the test. Expected: PASS.
- [ ] **Step 5: Commit** `chore: library mount and settings in compose and .env.example`.

### Task 10: Handheld folder map from the same alias table

**Files (repo `birdroms-handheld`):**
- Create: `internal/platforms/platform_aliases.csv` (the same CSV)
- Modify: `internal/platforms/muos_folders.go` (build `folders` from the embedded CSV), `internal/platforms/muos_folders_test.go`

**Interfaces:**
- Produces: `Folder(platform string) (dir string, known bool)` is unchanged. It's backed by every CSV row with a non-empty `muos_folder` and `kind != non-game`, keyed by `canonical_platform`. Embed the CSV with `//go:embed` and parse it with `encoding/csv` once.

- [ ] **Step 1: Write failing tests:** the existing 22 mappings are unchanged; `Folder("Sega CD / Mega-CD") == ("MDCD", true)`; `Folder("Neo Geo") == ("NEOGEO", true)`; `Folder("Virtual Boy") == ("VB", true)`; `Folder("PICO-8") == ("PICO", true)`; `Folder("Apps")` is unknown (`_UNSORTED`, false).
- [ ] **Step 2:** Run `just test`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `just test`, `go vet ./...`, `just build`. Expected: PASS.
- [ ] **Step 5: Commit** (handheld repo) `feat: download folders for every platform the server can produce`.

### Task 11: Real-library verification (controller)

- [ ] Point the dev backend at the SD card read-only. In the git-ignored `backend/.env`, set `LIBRARY_ROOT=/Volumes/ROMS-RG35` and `LIBRARY_READ_ONLY=true`. Back up the dev DB with `pg_dump`.
- [ ] Run `uv run python manage.py migrate && uv run python manage.py scan_library`. Expected: about 5,535 added, unknown folders listed (expected none), skipped counts plausible.
- [ ] Spot-check in the browser: platforms list, covers from `Imgs`, a download keeps the exact file name, the admin status panel. On the handheld, browse a large platform and use Y to select all across pages.
- [ ] Re-run `scan_library`: all counters 0.
- [ ] Expected side effect: the 3 pre-existing dev ROMs live in the old upload storage (`roms/…`), not the library, so the first scan flags them missing (3 is below the guard's minimum). The `N64 Night` test playlist then shows 0 ROMs; the library's own copies of those games are new rows. That's the spec's "re-imported, not migrated".
