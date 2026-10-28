# Plan: clean titles on import, original filename preserved (item B)

Source: item B of `~/.claude-personal/plans/ok-i-had-grok-vast-peacock.md` (the umbrella plan for the four notes from the first device test). That section is the spec; this file is its task breakdown.

## Goal

Uploads no longer ask for a title. The server stores the uploaded file's **original name** (`filename`) and derives a clean display **title** plus a list of human-readable **tags** (region, revision, dump flags) from it. Every download (web and handheld) uses the original filename, because muOS/RetroArch key saves, states, box art and playlists to the ROM's file name. The UIs show the clean title with the tags as a muted line beneath it.

## Global constraints

- The title is display-only. **Every download uses `filename`** (falling back to the old title+extension logic only for rows without one).
- Do **not** add a `region` model field: `ROM.region` already exists and belongs to the ScreenScraper metadata scrape (`METADATA_FIELDS` in `cover_art.py`). The filename's region goes into `tags`. (Ruling: the plan's `region` would collide with the scraped field.)
- TDD: write the failing test first, see it fail, then implement. Every change has a test.
- Match the surrounding code style (comment density, naming). No new dependencies.
- Server repo `~/birdrom-world/birdROMs`, branch `feat/clean-titles` (from `main`). Handheld repo `~/birdrom-world/birdroms-handheld`, branch `feat/clean-titles` (from `feat/square-tiles`). Commit on these branches; never push, never merge.
- Server commands: backend `cd backend && uv run python manage.py test apps.roms` (whole suite: `uv run python manage.py test`), `uv run python manage.py makemigrations --check`; frontend `cd frontend && PATH="$HOME/.local/share/mise/shims:$PATH" yarn test` / `yarn lint` / `yarn build`. Postgres is native (role/db `birdroms`), no docker. Handheld: `just test`, `just build` (cross-compile; needs `sysroot/` + zig, present).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 1: `parse_rom_filename` (server, pure function)

Files: `backend/apps/roms/services.py`, tests in `backend/apps/roms/tests.py` (new `ParseRomFilenameTests` class).

Add to `services.py`:

```python
@dataclass(frozen=True)
class ParsedName:
    title: str
    tags: tuple[str, ...]

def parse_rom_filename(name: str) -> ParsedName: ...
```

Rules, in order:
1. Drop trailing extensions while the final suffix (case-insensitive) is in `SUPPORTED_EXTENSIONS` (so a doubled `.z64.z64` goes too). A name with an unsupported or no suffix keeps it (`"Dr. Mario"` stays `"Dr. Mario"`). Call the result the *stem*.
2. If the stem contains no space, replace `_` with a space.
3. Only when the extension (the first one dropped in step 1) is `.gba`, `.nds` or `.3ds`: strip a leading scene number matching `^\d{4}\s*-\s+`. (Not for other systems: `"1943 - The Battle of Midway"` is a real NES title.)
4. Collect every `( … )` and `[ … ]` group, left to right, and turn each into tags (rules below). The title is the stem with all groups removed, whitespace collapsed, and stray trailing ` -`/`_`/spaces trimmed.
5. No-Intro trailing article: `"Legend of Zelda, The - The Minish Cap"` → `"The Legend of Zelda - The Minish Cap"`; `"Game, A"` → `"A Game"`. Articles: The, A, An (case kept as written). The article is the `, X` immediately before the end or before the first ` - `.
6. If the title is empty, use the stem (after step 2) stripped; if that is empty too, use `name` stripped.
7. Tags are de-duplicated, first occurrence wins, order kept.

`( … )` groups: split on `,` and strip each token.
- If every token is a region code or region name, the group becomes ONE tag: the expanded names joined with `", "`. Codes: `U`/`US`→USA, `E`/`EU`→Europe, `J`/`JP`→Japan, `W`→World, `UE`→`USA, Europe`, `JU`→`Japan, USA`, `K`→Korea, `G`→Germany, `F`→France, `S`→Spain, `I`→Italy, `A`→Australia, `B`/`Br`→Brazil, `Ch`→China, `UK`→UK. Names kept as written (case-insensitive match): USA, Europe, Japan, World, Korea, Germany, France, Spain, Italy, Australia, Brazil, China, Asia, Canada, Netherlands, Sweden, UK.
- Else if every token is a two-letter language code (`^[A-Z][a-z]$`, at least two tokens): one tag, tokens joined with `", "` (`(En,Fr,De)` → `En, Fr, De`).
- Else the whole group is one tag, with these exact whole-group replacements (case-insensitive): `Proto` → `Prototype`, `Unl` → `Unlicensed`; everything else verbatim (stripped), e.g. `Rev 2`, `Beta`, `frieNDS`.

`[ … ]` groups (content stripped):
- `!` → `Verified good dump`
- `T+…` or `T-…` → `Translation`
- first char in `a b f h o p t` (lower-case) followed by nothing or anything starting with a digit/upper-case letter (`b`, `b1`, `h1C`, `t2`) → `a` Alternate, `b` Bad dump, `f` Fixed, `h` Hack, `o` Overdump, `p` Pirate, `t` Trained
- anything else verbatim.

Required test cases (input → title, tags):
- `"Bomberman 64 (U) [!].z64"` → `"Bomberman 64"`, `("USA", "Verified good dump")`
- `"Donkey Kong 64 (U) [!].z64.z64"` → `"Donkey Kong 64"`, `("USA", "Verified good dump")`
- `"6111 - Pokemon Black 2 (US) (frieNDS).nds"` → `"Pokemon Black 2"`, `("USA", "frieNDS")`
- `"1943 - The Battle of Midway (USA).nes"` → `"1943 - The Battle of Midway"`, `("USA",)`
- `"Legend of Zelda, The - The Minish Cap (USA).gba"` → `"The Legend of Zelda - The Minish Cap"`, `("USA",)`
- `"Super_Mario_World.sfc"` → `"Super Mario World"`, `()`
- `"Sonic the Hedgehog 2 (World) (Rev A).md"` → `"Sonic the Hedgehog 2"`, `("World", "Rev A")`
- `"Pokemon - Emerald Version (USA, Europe).gba"` → `"Pokemon - Emerald Version"`, `("USA, Europe",)`
- `"Some Game (Europe) (En,Fr,De) (Beta).gba"` → `"Some Game"`, `("Europe", "En, Fr, De", "Beta")`
- `"Hack Game (U) [h1C] [T+Eng1.0].nes"` → `"Hack Game"`, `("USA", "Hack", "Translation")`
- `"Proto Thing (Japan) (Proto) (Unl).gb"` → `"Proto Thing"`, `("Japan", "Prototype", "Unlicensed")`
- `"Duplicate (USA) (USA).gba"` → `"Duplicate"`, `("USA",)`
- `"(Beta).gba"` → `"(Beta)"`, `("Beta",)`
- `"Dr. Mario"` → `"Dr. Mario"`, `()`
- `"Bomberman 64 (U) [!]"` → `"Bomberman 64"`, `("USA", "Verified good dump")`

Also add one test in the cover-art tests: `normalize_title("Bomberman 64") == normalize_title("Bomberman 64 (U) [!]")` (a clean title matches like a tagged one).

Commit: `feat: parse clean titles and tags from ROM file names`.

### Task 2: store `filename` and `tags`; derive the title on upload (server)

Files: `backend/apps/roms/models.py`, new migration `0005_rom_filename_tags.py`, `serializers.py`, `views.py`, `tests.py`.

- Model `ROM`: `filename = models.CharField(max_length=255, blank=True, default="")` with a comment ("original upload name; every download uses it"), and `tags = models.JSONField(default=list, blank=True)`. Schema migration only (generated by `makemigrations`, named `0005_rom_filename_tags`).
- `ROMSerializer`: add `"filename"` and `"tags"` to `fields` and to `read_only_fields`; make `title` optional on input (`extra_kwargs = {"title": {"required": False, "allow_blank": True}}`). In `create(validated_data)`: take the uploaded file's original name (`os.path.basename(file.name)`), drop control characters (`[\x00-\x1f\x7f]`), replace `/` and `\` with `_`, strip, and truncate to 255 characters keeping the extension; store it as `filename`. Parse it with `parse_rom_filename`; `tags = list(parsed.tags)`; `title = ` the supplied title stripped if non-blank, else `parsed.title` (truncated to 255). Updates (PATCH/PUT) behave as today; `filename` and `tags` cannot be written.
- `DeviceROMSerializer.Meta.fields`: append `"filename"` and `"tags"` (order: `id, title, platform, extension, size_bytes, cover_url, filename, tags`).
- `ROMViewSet.get_queryset`: search matches `Q(title__icontains=search) | Q(filename__icontains=search)`.

Tests (API level, like the existing upload tests): upload `Bomberman 64 (U) [!].z64` with no title → 201, `title == "Bomberman 64"`, `filename == "Bomberman 64 (U) [!].z64"`, `tags == ["USA", "Verified good dump"]`; upload with `title="My Name"` → title kept, filename and tags still set from the file; blank title → derived; PATCH `title` changes only the title and a PATCH of `filename`/`tags` is ignored; the device listing (`?fields=device`) and a playlist detail include `filename` and `tags`; `?search=(U)` finds the ROM via its filename. `makemigrations --check` clean.

Commit: `feat: keep the original file name and derive a clean title and tags on upload`.

### Task 3: downloads and scraping use the original filename (server)

Files: `backend/apps/roms/views.py`, `backend/apps/roms/cover_art.py`, `tests.py`.

- `download_filename(rom)`: when `rom.filename` is non-blank after the same sanitizing as today (control characters removed, `/` and `\` → `_`, stripped), return it as-is (it already carries its extension). Otherwise keep the current title+extension logic and storage-key fallback unchanged. Update the docstring.
- `cover_art.scrape_rom`: pass `rom.filename or (rom.file.name if rom.file else "")` as the filename, so `_title_candidates` tries the original No-Intro stem rather than the sanitized storage key.

Tests: download of a ROM with `filename="Bomberman 64 (U) [!].z64"` and title `"Bomberman 64"` sends that exact filename in `Content-Disposition`; a ROM with a blank filename keeps today's behaviour (existing tests stay green); a filename containing CR/LF or `/` is sanitized; `scrape_rom` passes `rom.filename` to the scraper when set and the storage name when blank (mock `scrape_cover_art`/`ScreenScraperGame` the way existing tests do).

Commit: `feat: downloads and cover scraping use the original file name`.

### Task 4: backfill existing ROMs (server, data migration)

Files: new migration `backend/apps/roms/migrations/0006_backfill_rom_filenames.py`, tests in `tests.py`.

- Forward (`backfill`): for every ROM with a blank `filename`: `filename = title` if `extension` is non-empty and `title.lower().endswith(extension)`, else `title + extension`, truncated to 255. Then `parsed = parse_rom_filename(filename)`; set `title = parsed.title` (≤255), `tags = list(parsed.tags)`. Save with `update_fields`. Import `parse_rom_filename` from `apps.roms.services` (pure function; acceptable in a data migration).
- Reverse (`restore`): for every ROM with a non-blank `filename`: `title = filename[:255]`, `filename = ""`, `tags = []`.
- Use `apps.get_model("roms", "ROM")`; `migrations.RunPython(backfill, restore)`.

Tests: import the migration module with `importlib.import_module("apps.roms.migrations.0006_backfill_rom_filenames")` and call `backfill(django_apps, None)` / `restore(django_apps, None)` with `from django.apps import apps as django_apps`, on rows created with a blank filename: titles `"6111 - Pokemon Black 2 (US) (frieNDS).nds"` (ext `.nds`) → filename unchanged, title `"Pokemon Black 2"`, tags `["USA", "frieNDS"]`; `"Bomberman 64 (U) [!]"` (ext `.z64`) → filename `"Bomberman 64 (U) [!].z64"`; a row that already has a filename is left untouched; reverse restores `title == filename` and clears filename/tags.

Commit: `feat: backfill original file names and clean titles for existing ROMs`.

### Task 5: web upload without a title; tags line on the card (frontend)

Files: `frontend/src/App.jsx`, `frontend/src/styles.css`, `frontend/src/api/client.js`, tests in `frontend/src/App.test.jsx` (and `client.test.js` if it exists).

- `UploadPanel`: remove the title state, the "ROM title" input and `formData.append("title", …)`; the form uploads just the file. `GlobalDropzone.uploadBatch`: stop appending `title`.
- ROM card: under the `.rom-title` heading, when `rom.tags` is a non-empty array render `<p className="rom-tags">{rom.tags.join(" · ")}</p>`; render nothing otherwise (older API rows may lack `tags`). The heading's `title` attribute (hover tooltip) becomes `rom.filename || rom.title`.
- `styles.css`: `.rom-tags` — small (≈0.75rem), muted (`var(--color-text-dim)`), one line with ellipsis, margin 0.
- `client.js` download fallback name: `rom.filename || \`${rom.title}${rom.extension || ""}\`` (the server's `Content-Disposition` still wins).
- Tests: the upload form has no title input and posts FormData without `title`; the dropzone posts without `title`; a card with `tags: ["USA", "Verified good dump"]` shows `USA · Verified good dump`; a card without tags renders no `.rom-tags`; download fallback uses `filename`. `yarn test`, `yarn lint`, `yarn build` green.

Commit: `feat: upload without a title; show region and dump tags under the ROM title`.

### Task 6: handheld saves the original filename (handheld)

Files: `internal/api/client.go`, `internal/download/filename.go`, `internal/download/match.go`, tests next to them.

- `api.ROM`: add `Filename string \`json:"filename"\`` and `Tags []string \`json:"tags"\`` (both absent on old servers: zero values).
- `download.Filename(rom)`: when `strings.TrimSpace(rom.Filename) != ""`: `name := sanitize(rom.Filename)`; `ext := truncBytes(filepath.Ext(name), maxExtBytes)`; stem = `name` without `ext`, trimmed of spaces, truncated to `maxNameBytes-len(ext)`, then `TrimRight(stem, ". ")`; if the stem is non-empty return `stem + ext`, else fall through. Otherwise the existing title+extension path, unchanged. `idFilename` gets the same Filename branch, producing `stem + "-<id>" + ext`. Doc comments updated.
- `findExisting(dir, rom)`: before the normalized-name scan, look for a regular, non-dot file whose name equals `Filename(rom)` case-insensitively (`strings.EqualFold`) with exactly the server-reported size; return it. Then the existing normalized-title scan as today.
- Tests: `Filename` returns `"Bomberman 64 (U) [!].z64"` for `{Title: "Bomberman 64", Extension: ".z64", Filename: "Bomberman 64 (U) [!].z64"}`; sanitizes `:`/`/` in Filename; truncation keeps the extension; a Filename that sanitizes to only an extension falls back to the title path; empty Filename → old behaviour (existing tests unchanged); `idFilename` with Filename → `"Bomberman 64 (U) [!]-7.z64"`; `findExisting` finds `"bomberman 64 (u) [!].Z64"` of the right size for that ROM and rejects a wrong size; JSON decoding of a device ROM with `filename` and `tags`.

Commit: `feat: save ROMs under their original file name`.

### Task 7: handheld shows the tags line (handheld UI)

Files: `ui/browse/browse.go`, `ui/download/download.go`, `cmd/gridpreview/main.go`, `cmd/dlpreview/main.go`.

- Browse grid `drawCell`: under the title (Tiny font, at `y+boxH+8`), draw `strings.Join(rom.Tags, " · ")` in the Tiny font, `theme.Dimmed`, at `y+boxH+28`, fitted to `cellW-12` with `s.fit`; nothing when there are no tags. It must stay inside the cell (`cellH` = 190) and not touch the focus outline.
- Download screen hero card: show the same joined tags in Tiny `theme.Dimmed` within the hero card without overlapping the existing lines (title lines at `heroY+10`/`+38`, folder line at `heroY+68`, percentage at `heroY+86`, stats at `heroY+100`, bar at `heroY+132`, bytes at `heroY+150`). Choose a free position (e.g. the second title line's slot when the title fits on one line, otherwise append to the folder line with `"  ·  "`), and fit it to the available width.
- Give the fake ROMs in `cmd/gridpreview` and `cmd/dlpreview` realistic `Tags` (and `Filename`s) so the previews exercise the line.
- No SDL unit tests exist for these packages; verification is visual: run `go run ./cmd/gridpreview -shots <dir> -at 60,120` and `go run ./cmd/dlpreview -shots <dir> -at 150,600` and inspect the PNGs; also `go vet ./...`, `just test` and `just build` must pass. Put the screenshot paths in the report.

Commit: `feat: show region and dump tags under ROM titles on the handheld`.
