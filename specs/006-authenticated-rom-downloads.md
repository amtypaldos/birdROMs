# 006 — Authenticated ROM downloads

## Status: DRAFT
Priority: 6

## Problem / Context
ROM files are served directly from `/media/` (`birdroms/urls.py` + `rom.file` links), so the
URL is **public and unauthenticated** — anyone with a path can download a ROM, bypassing the
`readonly`/`super_admin` role model. Downloads must go through an authenticated,
permission-checked endpoint that works with either storage backend (spec 005).

## Acceptance Criteria
- `GET /api/roms/{id}/download/` returns the ROM only for authenticated users passing
  `IsSuperAdminOrReadOnlyRole`, with `Content-Disposition: attachment; filename="…"`.
  - Filesystem backend: stream the file.
  - S3-compatible backend: either stream through the app or issue a short-lived pre-signed URL
    redirect (document which; the client must not get a permanent public URL).
- Unauthenticated/unauthorized → 401/403; unknown id → 404.
- The serializer no longer exposes a permanent public media URL as the download path; the
  frontend "Download" uses the authenticated endpoint (fetch with token → blob download), not a
  bare `<a href=rom.file>`.
- In non-DEBUG mode, raw ROM media is not served by Django's `static()` route.
- Covered by backend tests (spec 001).

## Completion Signal
Implementation:
- [ ] `download` endpoint with permission + 404 + attachment header, storage-aware.
- [ ] Public media route removed/guarded for non-DEBUG.
- [ ] Frontend downloads via the authenticated endpoint with the token.

Testing:
- [ ] Backend tests: super_admin & readonly can download; anon denied; unknown id → 404.
- [ ] `uv run python manage.py test` passes; `yarn test`/`yarn build` pass.

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 0 -->
