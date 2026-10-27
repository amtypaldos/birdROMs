# Completion log — 004 Expanded platform & file-type support

**What I implemented:** `EXTENSION_TO_PLATFORM` in `backend/apps/roms/services.py` grew from
16 to 50 extensions. It covers every system the spec lists, plus generic "Disc Image"
(`.iso/.bin/.cue/.chd`) and "Archive" (`.zip/.7z`). The classifier now uses the final suffix
and ignores case. I added `get_extension`, `SUPPORTED_EXTENSIONS` and `SUPPORTED_PLATFORMS`,
and `ROM.save()` uses the shared helper. You can still override `platform` manually: it is only
auto-set when blank, and it stays writable through the API. The README now has the full
platform/extension table.

**How I verified it:** `uv run python manage.py test` runs 20 tests and all pass (8 are new).
They cover a sample across systems, ambiguous extensions, case and multi-dot names,
unknown or missing extensions, the derived constants, auto-classification on upload, an
explicit override on upload, and a PATCH correction. `makemigrations --check` reports no
changes. A script confirmed the README table matches the map exactly.

**Follow-up:** none for this spec. Push was skipped because the repo has no remote.
