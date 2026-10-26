# 001 — Backend test harness — complete

**Implemented:** test-mode settings (in-memory SQLite, temp MEDIA_ROOT), `apps/accounts/tests.py`
(register 201 + readonly group + token, short password 400, login valid/invalid),
`apps/roms/tests.py` (anon/readonly/no-role/super_admin permission matrix, multipart create
with extension/platform auto-populated, scrape_cover 404, settings sanity check), README Testing section.

**Verified:** `cd backend && uv run python manage.py test` → 12 tests, OK, run from a fresh
worktree with no `.env` and no Postgres reachable. Confirmed the tests failed against Postgres
before the settings change, and that no temp media dirs are left behind.

**Follow-up:** no git remote configured, so the commit was not pushed.
