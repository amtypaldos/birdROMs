# Self-hosting birdROMs with Docker

> Deploying with prebuilt images, an NFS or S3 library, behind an existing reverse proxy? See
> [docs/deploying.md](docs/deploying.md).

Docker is the recommended way to run birdROMs. The production stack in
[`docker-compose.prod.yml`](docker-compose.prod.yml) runs five containers:

| Service | Image | Role |
| --- | --- | --- |
| `postgres` | `postgres:16` | Database (named volume `birdroms_pgdata`) |
| `backend` | built from `backend/Dockerfile` (`prod` target) | Django + gunicorn. Runs `migrate` and `collectstatic` on every start. ROMs and cover art live in the named volume `birdroms_media`, or in S3. |
| `redis` | `redis:7-alpine` | Task queue broker for background jobs (cover-art scraping). Holds no data you need to keep. |
| `worker` | same image as `backend` | Runs `python manage.py run_huey`: consumes the queue and runs the hourly sweep that re-queues ROMs still missing cover art. Shares the env file and media volume with `backend`. |
| `web` | built from `frontend/Dockerfile` (`prod` target) | nginx. Serves the built React app and proxies `/api/`, `/admin/` and `/static/` to the backend. This is the only published port. |

Cover art is scraped in the background: an upload returns immediately and the `worker` fetches
the art shortly after. Without a running `redis` and `worker`, uploads still succeed but covers
never appear. The compose file sets `REDIS_URL=redis://redis:6379/0` for `backend` and `worker`
(overriding any value in `backend/.env`); if you run Redis elsewhere, change it in the compose file.

All configuration comes from one env file, `backend/.env`. No secrets are baked into the
images, and deploying needs no code changes.

## 1. Prerequisites

- A Linux host (or any machine) with **Docker Engine 24+** and the **Compose v2.24+** plugin
  (`docker compose version`).
- About 1 GB of RAM for the stack, plus disk space for your ROM library.
- A DNS name for the instance (e.g. `roms.example.com`) and a TLS-terminating reverse proxy
  if it will be reachable beyond a trusted LAN (see [step 5](#5-https-and-a-reverse-proxy)).

## 2. Get the code and configure the environment

```bash
git clone https://github.com/<you>/birdROMs.git && cd birdROMs
cp backend/.env.example backend/.env
```

Edit `backend/.env`. Every variable is documented inline. For production, set at least:

```env
DJANGO_SECRET_KEY=<output of: python3 -c "import secrets; print(secrets.token_urlsafe(50))">
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=roms.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://roms.example.com
DJANGO_BEHIND_HTTPS_PROXY=True        # when TLS terminates at a proxy in front of birdROMs

POSTGRES_DB=birdroms
POSTGRES_USER=birdroms
POSTGRES_PASSWORD=<a long random password>
```

If a TLS-terminating proxy sits in front of the `web` container, also set `NUM_PROXIES=2`
(default `1`: the `web` nginx only). It tells Django how many proxies to trust in
`X-Forwarded-For`, which the sign-up throttle uses to find the real client address.

`POSTGRES_*` configures both the database container (it creates the database on first start)
and the backend's connection. `POSTGRES_HOST`, `POSTGRES_PORT` and `MEDIA_ROOT` are fixed by the
compose file, so you can leave them as they are.

With `DJANGO_DEBUG=False` the backend will not start while `DJANGO_SECRET_KEY` is empty or
still a placeholder. Local login is off unless `AUTH_METHODS` includes `local` (or
`ALLOW_LOCAL_LOGIN=True`). The default `AUTH_METHODS=local` enables it.

Want the env file outside the checkout? Point Compose at it with
`BIRDROMS_ENV_FILE=/etc/birdroms/birdroms.env`.

A few knobs configure Compose itself rather than the app. Set them in your shell or in a
repo-root `.env` file, which Compose reads automatically:

| Variable | Default | Meaning |
| --- | --- | --- |
| `BIRDROMS_HTTP_PORT` | `8080` | Host port the `web` container is published on |
| `NGINX_CLIENT_MAX_BODY_SIZE` | `2g` | nginx upload limit. Keep it at least `MAX_ROM_UPLOAD_BYTES`. |
| `BIRDROMS_ENV_FILE` | `./backend/.env` | App env file |
| `BIRDROMS_BACKEND_IMAGE` / `BIRDROMS_WEB_IMAGE` | `birdroms-backend:latest` / `birdroms-web:latest` | Image tags to build or pull |

## 3. Start the stack

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps        # all five should become "healthy"/"running"
docker compose -f docker-compose.prod.yml logs -f backend
```

birdROMs is now on `http://<host>:8080`. The `web` container waits for the backend's health
check, which waits for PostgreSQL, so the first start can take a few seconds.

## 4. Bootstrap the first `super_admin`

Any Django superuser has the `super_admin` role. Create the first one with:

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

Sign in with that account in the web UI to upload ROMs, or at `/admin/` to manage users.
In the admin you assign roles by adding users to the `super_admin` or `readonly` group.

For an SSO-only setup, members of `OIDC_ADMIN_GROUP` become `super_admin` on their first
login (see [step 6](#6-single-sign-on-oidc--pocket-id-example)). You still need a
superuser to sign in to `/admin/` with a password. To create one without a prompt
(e.g. from automation):

```bash
docker compose -f docker-compose.prod.yml exec -e DJANGO_SUPERUSER_PASSWORD='<password>' \
  backend python manage.py createsuperuser --noinput --username admin --email admin@example.com
```

## 5. HTTPS and a reverse proxy

The `web` container speaks plain HTTP. Put a TLS-terminating proxy in front of it and set
`DJANGO_BEHIND_HTTPS_PROXY=True`. That makes Django trust the proxy's `X-Forwarded-Proto` and
mark cookies Secure. nginx inside the `web` container passes the original scheme and host
through. Example with [Caddy](https://caddyserver.com/), which also gets certificates
automatically:

```caddyfile
roms.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

With Traefik or another proxy on the same Docker network, you can remove the `web` service's
`ports:` and route to `web:80` instead. Raise the proxy's own upload limit and timeouts to
match `MAX_ROM_UPLOAD_BYTES`, since large disc images take a while to upload.

## 6. Single sign-on (OIDC) — Pocket ID example

1. In Pocket ID, go to **OIDC Clients → Add OIDC Client**. Name it `birdROMs` and set the
   **Callback URL** to `https://roms.example.com/api/auth/oidc/callback/`. Save it, then copy the
   client ID and secret.
2. Optional: create a group (e.g. `birdroms-admins`), add your admins to it, and allow the
   client to send groups.
3. Add to `backend/.env`:

   ```env
   AUTH_METHODS=oidc              # or local,oidc to keep password login too
   ALLOW_LOCAL_LOGIN=False
   OIDC_ISSUER=https://id.example.com
   OIDC_CLIENT_ID=<client id>
   OIDC_CLIENT_SECRET=<client secret>
   OIDC_REDIRECT_URI=https://roms.example.com/api/auth/oidc/callback/
   OIDC_LOGIN_REDIRECT_URL=https://roms.example.com/
   OIDC_ADMIN_GROUP=birdroms-admins
   OIDC_PROVIDER_NAME=Pocket ID
   ```

4. Apply the change with `docker compose -f docker-compose.prod.yml up -d`.

The backend container has to reach `OIDC_ISSUER` to fetch the discovery document. Authentik,
Keycloak, Authelia and Google use the same variables; see the README's
[Login methods](README.md#login-methods) section for provider-specific notes.

## 7. Storage: local volume, NFS, or S3/MinIO

**Default:** ROMs and cover art go to the `birdroms_media` named volume (`/data/media` in the
container).

**NFS / a host directory:** in `docker-compose.prod.yml`, replace
`birdroms_media:/data/media` with a bind mount such as `/mnt/roms:/data/media`. The container
runs as a non-root `birdroms` user (uid/gid `568`), so that user must be able to write to the
directory. Run `chown -R 568:568 /mnt/roms`, or set up your NFS export to match.

**S3-compatible (AWS S3, MinIO, Cloudflare R2, Backblaze B2):** create a private bucket and an
access key for it, then add to `backend/.env`. MinIO example:

```env
STORAGE_BACKEND=s3
S3_BUCKET_NAME=birdroms
S3_ACCESS_KEY_ID=<access key>
S3_SECRET_ACCESS_KEY=<secret key>
S3_ENDPOINT_URL=http://minio.example.lan:9000
S3_REGION=us-east-1
S3_PATH_STYLE=True
```

Objects are never made public. Downloads always stream through the permission-checked API.
To run MinIO next to birdROMs, add a `minio` service to the compose file (or an override
file) and use `S3_ENDPOINT_URL=http://minio:9000`.

## 8. Upgrades

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Migrations run automatically when the backend starts. Back up first (next section).

## 9. Backups and restore

Back up two things: the **database** and the **media** (if you use filesystem storage; with
S3, use your provider's bucket versioning or replication).

```bash
# Database
docker compose -f docker-compose.prod.yml exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > birdroms-$(date +%F).dump

# Media volume (ROMs + cover art)
docker run --rm -v birdroms_birdroms_media:/data:ro -v "$PWD":/backup alpine \
  tar czf /backup/birdroms-media-$(date +%F).tar.gz -C /data .
```

The volume name is `<project>_birdroms_media`. The project defaults to the directory name,
so check it with `docker volume ls`. Keep `backend/.env` backed up too, somewhere private:
it holds your secrets.

Restore into a fresh stack:

```bash
docker compose -f docker-compose.prod.yml create          # creates the containers and volumes
docker compose -f docker-compose.prod.yml up -d postgres
docker compose -f docker-compose.prod.yml exec -T postgres \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < birdroms-YYYY-MM-DD.dump
docker run --rm -v birdroms_birdroms_media:/data -v "$PWD":/backup alpine \
  sh -c 'tar xzf /backup/birdroms-media-YYYY-MM-DD.tar.gz -C /data && chown -R 568:568 /data'
docker compose -f docker-compose.prod.yml up -d
```

The backend container runs as uid/gid `568` (TrueNAS's `apps` account). Change it at runtime
with `PUID`/`PGID` in `backend/.env` or with compose `user:`. That is why the media
files are given back to `568:568`.

## 10. Smoke test

After deploying or upgrading:

1. `docker compose -f docker-compose.prod.yml config --quiet`: the compose file and env parse.
2. `docker compose -f docker-compose.prod.yml ps`: `backend` is `healthy` and `web` is running.
3. `curl -s https://roms.example.com/api/auth/config/` returns your enabled login methods, e.g.
   `{"methods":["local"]}`.
4. `https://roms.example.com/` loads the UI. Deep links such as `/anything` also load it
   (SPA fallback).
5. `https://roms.example.com/admin/` shows a styled login page. This means static files are
   served.
6. Sign in as your `super_admin` and upload a small ROM. It should appear in the library, and
   downloading it should give back the identical file.
7. `docker compose -f docker-compose.prod.yml logs worker` shows Huey running, and the uploaded
   ROM gets cover art within a few seconds (if the title is known to a configured provider).
8. Restart with `docker compose -f docker-compose.prod.yml restart`. The ROM is still there.

## Troubleshooting

- **`backend` keeps restarting:** run `docker compose -f docker-compose.prod.yml logs backend`.
  An `ImproperlyConfigured` error names the env variable to fix. Typical causes are a
  placeholder secret key, missing OIDC/S3 values, or a bad boolean.
- **Covers never appear:** check `docker compose -f docker-compose.prod.yml logs worker` and that
  `redis` is healthy. Uploads are not affected by a queue outage, and the hourly sweep re-queues
  any ROM still missing art once the worker is back.
- **`400 Bad Request`:** the hostname you're using isn't in `DJANGO_ALLOWED_HOSTS`.
- **`403 CSRF verification failed` on `/admin/`:** add your origin (with scheme) to
  `DJANGO_CSRF_TRUSTED_ORIGINS`. Behind HTTPS, also set `DJANGO_BEHIND_HTTPS_PROXY=True`.
- **`413 Request Entity Too Large` on upload:** raise `NGINX_CLIENT_MAX_BODY_SIZE` and your
  outer proxy's limit, along with `MAX_ROM_UPLOAD_BYTES`.
- **OIDC `redirect_uri` mismatch:** `OIDC_REDIRECT_URI` must match the callback registered at
  the provider exactly, including the trailing slash.

## Development stack

Contributors only need Docker:

```bash
docker compose up --build
```

This starts PostgreSQL, Django `runserver` on <http://localhost:8000> and the Vite dev server
on <http://localhost:5173>, with hot reload from `./backend` and `./frontend/src`.
`backend/.env` is optional here. The compose file pins the database and debug settings, so it
works without any config. Create an admin with
`docker compose exec backend python manage.py createsuperuser`. If a local PostgreSQL already
uses port 5432, run `BIRDROMS_DB_PORT=15432 docker compose up`. After changing dependencies,
run `docker compose up --build` again.
