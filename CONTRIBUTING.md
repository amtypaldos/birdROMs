# Contributing to birdROMs

Thanks for your interest in birdROMs! This guide covers local setup, running the tests,
and what we expect from a pull request.

## Prerequisites

The quickest setup needs only Docker: `docker compose up --build` runs the whole stack with
hot reload (see the README's Quick Start). To run things directly on your machine instead:

- Python 3 and [uv](https://docs.astral.sh/uv/) for the backend
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
one. If you add a new setting, add it to `.env.example` with a placeholder value and a
comment — never a real secret.

### Frontend (`frontend/`)

```bash
cd frontend
yarn install
yarn dev
```

The dev server expects the API at `http://localhost:8000/api`.

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
- **Respect the role model.** Changes must not widen what `readonly` users (or anonymous
  visitors) can see or download. Treat uploaded files as untrusted input.
- **No secrets.** Never commit `.env` files, credentials, or tokens. Deployment-specific
  values belong in environment variables, documented in `.env.example`.
- **No ROMs.** Do not commit ROM files or copyrighted game assets, including as test
  fixtures — generate small synthetic files in tests instead.

By contributing, you agree that your contributions are licensed under the project's
[MIT License](LICENSE).
