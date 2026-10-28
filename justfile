# birdROMs native dev commands. Local dev is fully native: no Docker (Docker is for
# prod/self-host only). Requires: just, uv, node + yarn (corepack), and a local PostgreSQL.
# Run `just` with no arguments to list recipes.

# Postgres connection used by db-init; override with e.g. `PGHOST=... just db-init`.
# db-init connects as your OS user (a superuser on Postgres.app / Homebrew installs);
# set PGUSER=postgres if your server needs that instead.

default:
    @just --list

# Create the birdroms role and database in local Postgres (safe to re-run).
db-init:
    psql -d postgres -v ON_ERROR_STOP=1 -tc "SELECT 1 FROM pg_roles WHERE rolname = 'birdroms'" | grep -q 1 || psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE birdroms LOGIN CREATEDB PASSWORD 'birdroms'"
    psql -d postgres -v ON_ERROR_STOP=1 -tc "SELECT 1 FROM pg_database WHERE datname = 'birdroms'" | grep -q 1 || createdb -O birdroms birdroms

# Apply Django migrations.
migrate:
    cd backend && uv run python manage.py migrate

# Run the Django dev server on :8000.
backend:
    cd backend && uv run python manage.py runserver

# Run the Vite dev server on :5173.
frontend:
    cd frontend && yarn dev

# Like `backend`, but reachable from other devices on the LAN (e.g. the handheld); `ip` is this machine's LAN address.
backend-lan ip=`ipconfig getifaddr en0`:
    cd backend && DJANGO_ALLOWED_HOSTS=localhost,{{ip}} uv run python manage.py runserver 0.0.0.0:8000

# Like `frontend`, but reachable from other devices on the LAN. Point the handheld's server_url at http://<lan-ip>:5173.
frontend-lan:
    cd frontend && VITE_LAN=1 yarn dev

# Run backend (Django, against local Postgres) and frontend (Vitest) tests.
test:
    cd backend && uv run python manage.py test
    cd frontend && yarn test

# Lint the frontend (ESLint). The backend has no linter configured.
lint:
    cd frontend && yarn lint
