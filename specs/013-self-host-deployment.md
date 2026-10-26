# 013 — Docker-first self-host deployment

## Status: COMPLETE
Priority: 13

## Problem / Context
Docker is a **first-class citizen** for birdROMs: running it (for development and in production)
should be a one-command, fully env-driven experience so anyone can self-host. The existing
`docker-compose.yml` is minimal and there is no production image or end-to-end guide. This spec
assembles everything configured in earlier specs (configurable auth, storage, scrapers) into the
blessed Docker deploy path.

## Acceptance Criteria
- **Dev**: `docker compose up` brings up the full stack (Postgres + backend + frontend) with
  sane defaults and hot-reload-friendly config, so a contributor needs only Docker to run birdROMs.
- **Production**: multi-stage `Dockerfile`s for backend (gunicorn; runs `migrate` +
  `collectstatic` on start) and frontend (built and served via nginx or WhiteNoise), plus a
  `docker-compose.prod.yml` wiring Postgres + backend + frontend/reverse proxy. **All** config is
  via env — no baked secrets, no code changes to deploy.
- `backend/.env.example` is complete end-to-end: Django secret/allowed-hosts/DEBUG, database,
  `AUTH_METHODS` + `ALLOW_LOCAL_LOGIN` + OIDC vars, `STORAGE_BACKEND` + S3 vars, ScreenScraper
  creds, `MAX_ROM_UPLOAD_BYTES`.
- `SELF_HOSTING.md` (linked prominently from the README as the recommended path) gives
  step-by-step Docker deploy: prerequisites, configuring env, `docker compose -f
  docker-compose.prod.yml up`, registering the OIDC client + redirect URI (Pocket ID example),
  pointing at S3/MinIO, bootstrapping the first `super_admin`, and backups.
- Both compose files validate: `docker compose config` and `docker compose -f
  docker-compose.prod.yml config` parse cleanly. The README makes Docker the primary quick-start.

## Completion Signal
Implementation:
- [x] Dev `docker compose up` runs the whole stack.
- [x] Production Dockerfiles + `docker-compose.prod.yml`, fully env-driven.
- [x] Complete `.env.example`.
- [x] `SELF_HOSTING.md` end-to-end Docker guide, linked as the recommended path from README.

Testing:
- [x] `docker compose config` and `docker compose -f docker-compose.prod.yml config` parse cleanly.
- [x] Backend + frontend test/build suites still pass.
- [x] Smoke test steps documented (and run if the environment allows).

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 1 -->
