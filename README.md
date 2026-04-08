# birdROMs

`birdROMs` is a Django + React web app for private retro ROM sharing and management with role-based access, extension-based ROM classification, and cover art scraping support.

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

## Auth and Roles

Roles are implemented as user groups:

- `super_admin`: create/edit/delete ROMs, upload files, scrape cover art
- `readonly`: list ROMs and download files

Use Django admin to assign users to these groups after signup/creation.

## ROM Classification

ROM classification is determined server-side from file extension. Unknown extensions are tagged as `unknown`.

## Cover Art Scraping

`POST /api/roms/{id}/scrape-cover/` attempts to fetch cover art metadata based on ROM title/platform. The initial implementation provides a service hook and safe fallback, ready for integration with providers such as IGDB, ScreenScraper, or custom scrapers.

## Important Note About Git Init

If your environment blocks `.git` writes, run this manually from the project root:

```bash
cd birdROMs
git init
```
