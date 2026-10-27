# Completion — 013 self-host-deployment

## Implemented
- `docker-compose.yml` (dev): postgres (healthcheck, `BIRDROMS_DB_PORT`), backend `dev` target
  (runserver, `./backend` bind mount, optional backend/.env, pinned DB/debug), frontend `dev`
  target (Vite with `VITE_PROXY_TARGET=http://backend:8000`, src bind mounts).
- `backend/Dockerfile` (deps → base → dev/prod), `docker-entrypoint.sh` (migrate, collectstatic,
  gunicorn gthread), `docker-healthcheck.py`, `.dockerignore`. gunicorn + whitenoise deps.
- `frontend/Dockerfile` (deps → dev / build → nginx prod), `nginx/default.conf.template`,
  `.dockerignore`. `packageManager` pinned; Vite proxy target is env-configurable.
- `docker-compose.prod.yml`: postgres + backend + web, all config from `backend/.env`.
- `birdroms/deploy_config.py` + settings wiring (CSRF origins, HTTPS proxy, secure cookies,
  STATIC_ROOT, secret-key guard) and `birdroms/tests.py` (7 tests).
- `backend/.env.example` extended. `SELF_HOSTING.md` added. README is Docker-first with
  SELF_HOSTING linked prominently. CONTRIBUTING mentions Docker. `staticfiles/` gitignored.

## Verified
- `docker compose config --quiet` and `docker compose -f docker-compose.prod.yml config --quiet` OK.
- Backend: 113 tests OK. Frontend: lint clean, 29 tests pass, `yarn build` OK.
- Prod smoke (throwaway env via `BIRDROMS_ENV_FILE`, port 18080): all containers healthy. SPA +
  deep-link fallback, `/api/auth/config/`, admin login page, and admin CSS via WhiteNoise all
  load. Register/login works. `createsuperuser --noinput` gives role `super_admin`. A 5 MB
  upload through nginx works. Download is byte-identical, also after `down`/`up`. Placeholder
  secret with DEBUG=False fails fast. pg_dump + media tar backup → `down -v` → restore →
  download is byte-identical.
- Dev smoke: UI on 5173, API direct and through the Vite proxy, backend autoreload, and Vite
  serving edited src all work.

## Follow-ups
- See history note: split the postgres env, and publish images from CI (spec 014).
- Push skipped: no git remote is configured (same as earlier specs).
