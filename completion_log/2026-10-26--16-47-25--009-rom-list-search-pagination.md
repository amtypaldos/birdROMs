# 009 — ROM list pagination, search & platform filter

**Implemented:** paginated `GET /api/roms/` (`count/next/previous/results`, 24 per page, `page_size`
max 100). Case-insensitive partial `?search=` on title and exact `?platform=`, which can be
combined. New `GET /api/roms/platforms/`. Frontend: search box, platform dropdown, Previous/Next
with page/count summary, and a "No ROMs found." empty state. `api.listRoms(query)` handles the
envelope and there is a new `api.listPlatforms()`. README has a "Browsing the library" section.

**Verified:** `uv run python manage.py test` gives 86 tests OK. `yarn test` gives 20 passed.
`yarn lint` is clean and `yarn build` succeeds.

**Follow-up:** none required. Spec 011/012 can restyle the filter bar and pagination.
