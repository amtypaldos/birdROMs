# 013 — Docker-first self-host deployment

## Decisions
- **One env file** (`backend/.env`) configures both the `postgres` and `backend` prod
  containers (same `POSTGRES_*` names). `BIRDROMS_ENV_FILE` overrides the path; compose-level
  knobs (`BIRDROMS_HTTP_PORT`, `NGINX_CLIENT_MAX_BODY_SIZE`, image tags) come from the shell or a
  repo-root `.env`. `env_file` uses `required: false` so `docker compose config` parses on a
  fresh clone (needs Compose ≥ 2.24).
- **nginx in the web image** serves the SPA and proxies `/api|/admin|/static` to gunicorn, so the
  frontend keeps its default same-origin `VITE_API_BASE=/api` with no build-time config. The
  template uses the nginx image's envsubst (only defined env vars are substituted, so `$host`
  etc. are safe). Forward `$http_host`, not `$host`: `$host` drops the port, and DRF built
  `download_url` as `http://localhost/...` (caught in the smoke test).
- **gunicorn gthread** workers (env `GUNICORN_WORKERS/THREADS/TIMEOUT`) so multi-GB uploads and
  streamed downloads don't trip the sync-worker timeout.
- **WhiteNoise** serves Django admin static after `collectstatic` (run in the entrypoint on
  every start, per spec). ROM media is never static.
- New `birdroms/deploy_config.py`: `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_BEHIND_HTTPS_PROXY`
  (→ `SECURE_PROXY_SSL_HEADER` + Secure cookies), and `check_secret_key`, which refuses to
  start with DEBUG off and an empty/placeholder secret (skipped under `manage.py test`).
- The backend venv lives at `/opt/venv` (`UV_PROJECT_ENVIRONMENT`) so the dev bind mount of
  `./backend:/app` doesn't hide it behind the host's macOS `.venv`.
- **Yarn PnP in Docker:** pinned `packageManager: yarn@4.18.0` (corepack would otherwise pick
  Yarn 1) and `YARN_ENABLE_GLOBAL_CACHE=false` in the image. The dev frontend container
  bind-mounts only `src/`, `index.html` and `vite.config.js`, never the project root, because the
  host's `.pnp.cjs` / `.yarn` point at the host's global cache and darwin binaries.
  Dependency changes need `docker compose up --build`.
- Dev compose publishes Postgres on `${BIRDROMS_DB_PORT:-5432}` (a local Postgres held 5432 on
  the build machine).
- Non-root `birdroms` user pinned to uid/gid 999. The NFS and restore docs depend on that.

## Issues
- zsh doesn't word-split `$C` command strings. Use a shell function for repeated compose calls.
- Vite/esbuild strips comments, so a hot-reload probe has to be a real statement.

## Follow-ups
- The prod `postgres` container also gets the app's other env (OIDC/S3 secrets) through the
  shared env file. That is harmless but broader than needed; a split env file would tighten it.
- No published images yet (CI in spec 014 could build/push `BIRDROMS_*_IMAGE`).
