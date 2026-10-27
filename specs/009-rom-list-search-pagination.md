# 009 — ROM list pagination, search & platform filter

## Status: COMPLETE
Priority: 9

## Problem / Context
`GET /api/roms/` returns **every** ROM with no pagination, search, or filtering, and the
frontend renders the whole list at once. Add server-side pagination plus title search and
platform filtering, and wire the frontend to use them.

## Acceptance Criteria
- DRF pagination enabled (default page size e.g. 24); list returns a paginated envelope
  (`count`, `next`, `previous`, `results`).
- `?search=` filters by title (case-insensitive, partial); `?platform=` filters exact platform;
  both combine.
- `GET /api/roms/platforms/` returns the distinct platforms present (for a filter dropdown).
- Frontend: a search box + platform dropdown drive the list, with pagination controls
  (prev/next or "load more"); Refresh still works. `api.listRoms` handles the envelope.
- Covered by backend tests (spec 001) and a frontend test (spec 002).

## Completion Signal
Implementation:
- [x] Pagination + `search` + `platform` filters; combinable.
- [x] Distinct-platforms endpoint.
- [x] Frontend search/filter/pagination UI.

Testing:
- [x] Backend tests: envelope shape; search narrows; platform filter works.
- [x] `uv run python manage.py test`, `yarn test`, `yarn lint`, `yarn build` pass.

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 1 -->
