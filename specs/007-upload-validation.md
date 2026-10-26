# 007 — ROM upload validation

## Status: COMPLETE
Priority: 7

## Problem / Context
ROM creation accepts **any file** with no validation. There is no extension allowlist, size
limit, or empty-file check. Uploads are untrusted and should be validated with clear 400 errors.
The allowlist derives from the expanded platform map (spec 004).

## Acceptance Criteria
- Uploads are restricted to the known extension allowlist derived from the spec-004 platform
  map (plus `.zip`/`.7z` archives). Unknown extensions → 400 with a clear field error.
- A configurable max upload size (`MAX_ROM_UPLOAD_BYTES`, default e.g. 2 GB, env-overridable) is
  enforced → 400 when exceeded. (Large ROMs like disc images are expected; pick a generous default.)
- Zero-byte files → 400.
- Validation lives in the serializer (DRF field errors) and does not break auto-classification
  of `platform`/`extension`.
- The final allowlist + size default are documented in `.env.example`/README.
- Covered by backend tests (spec 001).

## Completion Signal
Implementation:
- [x] Allowlist enforced from the platform map; archives included.
- [x] Env-configurable max size enforced.
- [x] Empty-file rejection.

Testing:
- [x] Backend tests: valid `.nes` ok; `.exe` → 400; oversized → 400; empty → 400.
- [x] `uv run python manage.py test` passes.

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 1 -->
