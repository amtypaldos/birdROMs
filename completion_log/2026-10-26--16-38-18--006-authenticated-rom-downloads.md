# 006 — Authenticated ROM downloads

**Implemented:** `GET /api/roms/{id}/download/` (IsSuperAdminOrReadOnlyRole, 404 for unknown ids,
attachment header, streamed from storage so it works with fs and S3), removed the public `/media/`
route, serializer `file` → write-only plus `download_url`, frontend Download button → token fetch →
blob save. README "Downloads" section.

**Verified:** `uv run python manage.py test` → 34 tests OK; `yarn test` → 7 passed; `yarn lint`
clean; `yarn build` OK.

**Follow-up:** optional pre-signed S3 redirect mode for large files; a serving path for stored cover art (spec 010).
