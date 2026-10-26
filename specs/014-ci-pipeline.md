# 014 — CI pipeline (GitHub Actions)

## Status: DRAFT
Priority: 14 (lowest)

## Problem / Context
There is **no CI**, which matters more now that Ralph pushes to `main` autonomously and the
project is meant to accept outside contributions. Add GitHub Actions running the backend tests
and the frontend lint/build/test on every push and PR. Depends on specs 001 and 002.

## Acceptance Criteria
- `.github/workflows/ci.yml` runs on `push` and `pull_request`.
- Backend job: Python 3.11+, install `uv`, sync deps, run `uv run python manage.py test` using
  the SQLite test DB from spec 001 (no external Postgres service needed).
- Frontend job: set up Node + corepack/yarn, install, run `yarn lint`, `yarn test`, `yarn build`.
- Optionally builds the production Docker image from spec 013 to catch build breakage.
- Valid YAML; the exact commands the workflow runs all pass locally from a clean checkout.
- A CI badge/section is added to the README.

## Completion Signal
Implementation:
- [ ] `ci.yml` with backend + frontend jobs on push/PR.
- [ ] Backend job runs tests without external Postgres; frontend runs lint/test/build.
- [ ] README mentions CI.

Testing:
- [ ] The exact workflow commands all pass locally from a clean checkout.
- [ ] `ci.yml` parses as valid YAML.

Commit and push. When every spec in `specs/` is COMPLETE, output `<promise>ALL_DONE</promise>`.

<!-- NR_OF_TRIES: 0 -->
