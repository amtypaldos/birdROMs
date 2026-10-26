# birdROMs

`birdROMs` is a Django + React web app for private retro ROM sharing and management with role-based access, extension-based ROM classification, and cover art scraping support.

## Self-hosting / Open source

birdROMs is free and open-source software. There is no central service: anyone can run
their own private instance for themselves and a trusted group. Every deployment-specific
value (database, secret key, allowed hosts, and future auth/storage settings) is configured
through environment variables documented in `backend/.env.example` — no secrets live in
this repository. Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Core Features

- Upload and manage ROM files in a shared library
- Role-based auth:
  - `super_admin`: full upload/manage access
  - `readonly`: browse metadata and download ROMs
- ROM platform classification from file extension (`.nes`, `.sfc`, `.gba`, etc.)
- Cover art scraping endpoint and metadata storage
- PostgreSQL as the primary database
- REST API backend (Django REST Framework) + React frontend

## Tech Stack

- Backend: Django, Django REST Framework, PostgreSQL
- Frontend: React + Vite
- Auth: Django auth + token-based API auth
- Storage: local media storage by default (`MEDIA_ROOT`)

## Project Structure

- `backend/`: Django API server
- `frontend/`: React client

## Quick Start

### 1) Backend setup (uv)

```bash
cd backend
uv venv
source .venv/bin/activate
uv sync
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### 2) Frontend setup (yarn)

```bash
cd frontend
yarn install
yarn dev
```

Frontend expects backend API at `http://localhost:8000/api`.

If Yarn is not already available, run `corepack enable` once.

## Testing

Backend tests run against an in-memory SQLite database and a temporary media directory,
so no PostgreSQL server (and no `.env`) is needed:

```bash
cd backend
uv run python manage.py test
```

Frontend lint and tests (ESLint + Vitest/React Testing Library on jsdom, no backend needed):

```bash
cd frontend
yarn lint
yarn test
```

## Auth and Roles

Roles are implemented as user groups:

- `super_admin`: create/edit/delete ROMs, upload files, scrape cover art
- `readonly`: list ROMs and download files

Use Django admin to assign users to these groups after signup/creation.

## ROM Classification

ROM classification is determined server-side from file extension. Unknown extensions are tagged as `unknown`.

## Cover Art Scraping

`POST /api/roms/{id}/scrape-cover/` attempts to fetch cover art metadata based on ROM title/platform. The initial implementation provides a service hook and safe fallback, ready for integration with providers such as IGDB, ScreenScraper, or custom scrapers.

## License

birdROMs is released under the [MIT License](LICENSE).

birdROMs does not ship or distribute any ROMs. You are responsible for ensuring that any
files you upload to your instance are ones you have the right to use and share.
