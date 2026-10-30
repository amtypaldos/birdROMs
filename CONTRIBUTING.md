# Contributing to birdROMs

Thanks for your interest in birdROMs! This guide covers local setup, running the tests,
and what we expect from a pull request. Please also read the [Code of Conduct](CODE_OF_CONDUCT.md);
report security problems privately as described in [SECURITY.md](SECURITY.md), not in a public issue.

## Prerequisites

The quickest setup needs only Docker: `docker compose up --build` runs the whole stack with
hot reload (see the README's Development section). To run things directly on your machine instead:

- Python 3.11+ (CI uses 3.12) and [uv](https://docs.astral.sh/uv/) for the backend
- Node.js with corepack (run `corepack enable` once to get Yarn) for the frontend
- A local PostgreSQL server (`just db-init` creates the `birdroms` role and database)
- [just](https://github.com/casey/just) for the shortcuts in the root `justfile`
  (`db-init`, `migrate`, `backend`, `frontend`, `test`, `lint`)

## Local development

### Backend (`backend/`)

```bash
cd backend
uv sync
cp .env.example .env   # .env is git-ignored; never commit it
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

All configuration comes from environment variables; `backend/.env.example` documents each
one. Running natively (not in Docker), set `LIBRARY_ROOT` in `.env` to a folder you can write to,
for example `LIBRARY_ROOT=$HOME/roms-library`; the default `/library` only exists in the containers. If you add a new setting, add it to `.env.example` with a placeholder value and a
comment — never a real secret.

### Frontend (`frontend/`)

```bash
cd frontend
yarn install
yarn dev
```

The Vite dev server proxies `/api` to `http://localhost:8000`. CI uses Node 24 (Node 22 hits a
jsdom/vitest module-linking error).

## Running the tests

Backend tests run on PostgreSQL (Django creates a `test_birdroms` database; `just db-init`
sets up the role) and a temporary media directory, so they need no `.env`. `just test` runs
the backend and frontend suites together:

```bash
cd backend
uv run python manage.py test
```

Frontend lint, tests, and build:

```bash
cd frontend
yarn lint
yarn test
yarn build
```

## Pull request expectations

- **Tests and lint must pass.** Run the backend test suite and `yarn lint`, `yarn test`,
  and `yarn build` before opening a PR.
- **Ship tests with your change.** New behavior and bug fixes should come with tests that
  cover them.
- **Keep PRs focused.** One logical change per PR, with a clear description of what and why.
- **Compose and Docker changes** should keep `scripts/check-compose.sh` passing.
- **Respect the role model.** Changes must not widen what `readonly` users (or anonymous
  visitors) can see or download. Treat uploaded files as untrusted input.
- **No secrets.** Never commit `.env` files, credentials, or tokens. Deployment-specific
  values belong in environment variables, documented in `.env.example`.
- **No ROMs.** Do not commit ROM files, BIOS files or copyrighted game assets, including as test
  fixtures. Generate small synthetic files in tests instead.

## Releases

The server and the handheld app are released on their own. Both use date tags:
`vYYYY.MM.DD`, and `vYYYY.MM.DD.N` when there is another release the same day.

[`handheld-version`](handheld-version) in this repo names the handheld release bundled
into the server image. A push to `main` and a server release tag both download
`birdROMs.muxapp` from that release. The server's own tag does not have to match it.

- The handheld app changed. Tag `birdroms-handheld` (`birdROMs handheld YYYY.MM.DD`).
  When that GitHub release exists, set `handheld-version` to the same tag. Tag this
  repo (`birdROMs YYYY.MM.DD`) when that image should ship.
- Only the site changed. Tag this repo and leave `handheld-version` as it is.

Paired devices update from the package published on the server, not from GitHub.
See [docs/handheld-app.md](docs/handheld-app.md).

By contributing, you agree that your contributions are licensed under the project's
[MIT License](LICENSE).
