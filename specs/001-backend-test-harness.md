# 001 — Backend test harness + auth & ROM API tests

## Status: COMPLETE
Priority: 1 (highest)

## Problem / Context
The backend has **no automated tests** and the default DB is PostgreSQL, so there is
currently no way to verify behavior without a running Postgres. The constitution requires
that every change ship with tests and leave `main` runnable. This spec establishes the
backend test foundation that every later spec depends on.

Relevant code: `backend/birdroms/settings.py`, `backend/apps/accounts/`, `backend/apps/roms/`.

## Acceptance Criteria
- Backend tests run with a single command and **do not require a running PostgreSQL** — tests
  use an in-memory/SQLite database (e.g. detect test runs in settings, or a `settings_test`
  module). Media writes during tests go to a temp dir, not the real `MEDIA_ROOT`.
- `cd backend && uv run python manage.py test` (or the documented equivalent) runs green.
- Tests cover accounts:
  - register creates a user, assigns the `readonly` group, and returns a token (201).
  - register rejects a password shorter than 8 chars (400).
  - login with valid credentials returns a token; invalid credentials return 400.
- Tests cover ROM API permissions using DRF's `APIClient`:
  - anonymous request to list/create ROMs → 401/403.
  - a `readonly` user can list ROMs but gets 403 on create.
  - a `super_admin` user can create a ROM (multipart upload of a small dummy file) and the
    saved ROM has `extension` and `platform` auto-populated from the filename.
  - `scrape_cover` returns 404 when the placeholder scraper yields no image.
- Test files live under each app (`apps/accounts/tests.py` / `apps/roms/tests.py` or a `tests/`
  package). A short "Testing" section is added to the README documenting the test command.

## Completion Signal
Implementation:
- [x] Test DB configured so tests run without Postgres.
- [x] Accounts tests written (register/login happy + error paths).
- [x] ROMs tests written (permission matrix + create + scrape_cover).
- [x] README documents how to run backend tests.

Testing:
- [x] `uv run python manage.py test` passes with 0 failures/errors from a clean checkout
      (no Postgres running).
- [x] New tests actually assert the behaviors above (not empty/placeholder).

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 1 -->
