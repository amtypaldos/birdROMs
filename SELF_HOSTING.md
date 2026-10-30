# Self-hosting birdROMs with Docker

> This is the walk-through for a first install. For the production runbook (prebuilt images, an NFS
> or S3 library, an existing reverse proxy, backups, updates and rollback) see
> [docs/deploying.md](docs/deploying.md).

Docker is the recommended way to run birdROMs. The production stack in
[`docker-compose.prod.yml`](docker-compose.prod.yml) runs five containers:

| Service | Image | Role |
| --- | --- | --- |
| `postgres` | `postgres:16` | Database (named volume `birdroms_pgdata`) |
| `backend` | built from `backend/Dockerfile` (`prod` target), or the prebuilt `ghcr.io/amtypaldos/birdroms-backend` image | Django + gunicorn. Runs `migrate` and `collectstatic` on every start. Your ROM library is mounted at `/library` (volume `birdroms_library` by default); scraped cover art and the handheld package go to the volume `birdroms_media` (or S3). |
| `redis` | `redis:7-alpine` | Task queue broker for background jobs (library scans, cover-art scraping). Holds no data you need to keep. |
| `worker` | same image as `backend` | Runs `python manage.py run_huey`: consumes the queue, rescans the library every 15 minutes and runs the hourly sweep that re-queues ROMs still missing cover art. Shares the env file and volumes with `backend`. |
| `web` | built from `frontend/Dockerfile` (`prod` target) | nginx. Serves the built React app and proxies `/api/`, `/admin/` and `/static/` to the backend. This is the only published port. |

The library is scanned and cover art is scraped in the background: an upload returns immediately and
the `worker` fetches the art shortly after. Without a running `redis` and `worker`, uploads still
succeed but covers never appear and files you copy into the library are not picked up (run
`manage.py scan_library` by hand to import them). The compose file sets `REDIS_URL=redis://redis:6379/0` for `backend` and `worker`
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
git clone https://github.com/amtypaldos/birdROMs.git && cd birdROMs
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
`X-Forwarded-For`, which the login, sign-up and invite throttles use to find the real client address.

`POSTGRES_*` configures both the database container (it creates the database on first start)
and the backend's connection. `POSTGRES_HOST`, `POSTGRES_PORT` and `MEDIA_ROOT` are fixed by the
compose file, so you can leave them as they are.

With `DJANGO_DEBUG=False` the backend will not start while `DJANGO_SECRET_KEY` is empty or
still a placeholder. Local login is off unless `AUTH_METHODS` includes `local` (or
`ALLOW_LOCAL_LOGIN=True`). The default `AUTH_METHODS=local` enables it. Self-registration is
separate and closed by default: create users in `/admin/`, or open sign-up with
`ALLOW_REGISTRATION=true` (or by ticking *Registration settings* in `/admin/` while the variable
is unset; a non-empty `ALLOW_REGISTRATION` overrides the checkbox).

Web sign-in uses an HttpOnly session cookie (14 days, renewed on activity; change it with
`SESSION_COOKIE_AGE`, in seconds) with CSRF protection, so `DJANGO_CSRF_TRUSTED_ORIGINS` and
`DJANGO_BEHIND_HTTPS_PROXY=True` must match how you reach the site. Handheld device tokens are unchanged,
read-only, and stop working after `DEVICE_TOKEN_IDLE_DAYS` of disuse (default 365, `0` = never).

Want the env file outside the checkout? Point Compose at it with
`BIRDROMS_ENV_FILE=/etc/birdroms/birdroms.env`.

A few knobs configure Compose itself rather than the app. Set them in your shell or in a
repo-root `.env` file, which Compose reads automatically:

| Variable | Default | Meaning |
| --- | --- | --- |
| `BIRDROMS_HTTP_PORT` | `8080` | Host port the `web` container is published on |
| `NGINX_CLIENT_MAX_BODY_SIZE` | `2g` | nginx upload limit. Keep it at least `MAX_ROM_UPLOAD_BYTES`. |
| `BIRDROMS_ENV_FILE` | `./backend/.env` | App env file |
| `BIRDROMS_BACKEND_IMAGE` / `BIRDROMS_WEB_IMAGE` | `birdroms-backend:latest` / `birdroms-web:latest` | Image tags to build or pull. Set them to `ghcr.io/amtypaldos/birdroms-backend:latest` and `ghcr.io/amtypaldos/birdroms-web:latest` for the prebuilt amd64/arm64 images (see [docs/deploying.md](docs/deploying.md#1-images)). |
| `PUID` / `PGID` | `1000` | User and group the backend and worker run as; set in `backend/.env`. Match the owner of your library folder. TrueNAS `apps` is 568. |

## 3. Start the stack

```bash
docker compose -f docker-compose.prod.yml up -d --build     # or `pull` then `up -d` with the prebuilt images
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

Sign in with that account in the web UI to upload ROMs and manage the library, or at `/admin/` to
manage users. In the admin you assign roles by adding users to the `super_admin`, `member` or `readonly` group.

To bring in a friend without opening self-registration, make an invite link. It works once and expires
after `INVITE_TTL_DAYS` (default 7):

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py create_invite --base-url https://roms.example.com --label "Sam"
```

(`--role super_admin` makes an admin and `--role member` someone who can upload but not delete; the default is `readonly`.) Signed in as an admin you can also use
**Invite a friend** on the Library page. The link is shown once and cannot be recovered; revoke an unused
one in `/admin/` under *Accounts > Invites*.

For an SSO-only setup, members of `OIDC_ADMIN_GROUP` become `super_admin` (and members of the optional `OIDC_MEMBER_GROUP` `member`) on their first
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

## 7. Your ROM library: volume, host folder, NFS, or S3

birdROMs reads games from a **library**: a folder (or S3 bucket) laid out the way muOS expects,
`ROMS/<SYSTEM>/<game file>`, with box art in `ROMS/<SYSTEM>/Imgs/`. It indexes the files where they
are (it never copies, moves, renames, overwrites or deletes them), rescans every 15 minutes, and
writes new uploads and scraped cover art into it.

**Default:** an empty `birdroms_library` named volume, mounted at `/library`. Fill it with the upload
page, or copy files into the volume.

**A folder on the host:** in `docker-compose.prod.yml` replace `birdroms_library:/library` with a bind
mount such as `/srv/roms:/library`. The container runs as `PUID`:`PGID` (default `1000:1000`), which must be
able to write there: `chown -R 1000:1000 /srv/roms`, or set `PUID`/`PGID` in `backend/.env` to the folder's
owner. If you never want birdROMs to write to your library, set `LIBRARY_READ_ONLY=true` (uploads and
cover write-back are then off).

**NFS:** add the `docker-compose.nfs.yml` override; see [docs/deploying.md](docs/deploying.md#3-the-library).

**S3-compatible (AWS S3, MinIO, Cloudflare R2, Backblaze B2):** create a private bucket and an access
key for it, then add to `backend/.env`. MinIO example:

```env
STORAGE_BACKEND=s3
S3_BUCKET_NAME=birdroms
S3_ACCESS_KEY_ID=<access key>
S3_SECRET_ACCESS_KEY=<secret key>
S3_ENDPOINT_URL=http://minio.example.lan:9000
S3_REGION=us-east-1
S3_PATH_STYLE=True
LIBRARY_S3_PREFIX=library/      # keep the library apart from other bucket content
```

Objects are never made public. Downloads always stream through the permission-checked API. To run
MinIO next to birdROMs, add a `minio` service to the compose file (or an override file) and use
`S3_ENDPOINT_URL=http://minio:9000`.

The first scan runs within 15 minutes of starting the worker. To run it right away:
`docker compose -f docker-compose.prod.yml exec backend python manage.py scan_library`.

Upgrading from the older upload-only storage? Read
[docs/upgrading-to-the-library.md](docs/upgrading-to-the-library.md).

## 8. Handheld app (optional)

To let friends install the muOS app from your server, publish the package once:
[docs/handheld-app.md](docs/handheld-app.md).

## 9. Updates, backups and restore

[docs/deploying.md](docs/deploying.md#8-backups) has the backup, restore, update and rollback
procedures. In short: back up the database (`pg_dump`), your library (with the storage system it
lives on), the `birdroms_media` volume and `backend/.env`, then
`docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d`
(or `git pull` and `up -d --build` when building from source). Migrations run on start.

## 10. Smoke test

After deploying or upgrading, run through [the smoke test](docs/deploying.md#7-smoke-test).

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
- **Uploads fail with "permission denied" or the library page says it is read-only:** the container
  user (`PUID`:`PGID`, default `1000:1000`) cannot write to the library. Fix the folder's ownership or
  change `PUID`/`PGID`; see [step 7](#7-your-rom-library-volume-host-folder-nfs-or-s3).
- **A scan aborted with a safety warning:** it would have hidden more than 25% of your ROMs, which
  usually means the library is not mounted. Check the mount first; see
  [docs/deploying.md](docs/deploying.md#first-scan).
- **OIDC `redirect_uri` mismatch:** `OIDC_REDIRECT_URI` must match the callback registered at
  the provider exactly, including the trailing slash.

## Development stack

Contributors: see [CONTRIBUTING.md](CONTRIBUTING.md). `docker compose up --build` starts a hot-reload
dev stack without any configuration.
