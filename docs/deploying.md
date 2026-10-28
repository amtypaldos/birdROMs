# Deploying birdROMs

A production runbook for any Docker host. It covers prebuilt images, an NFS or S3 library, a
reverse proxy in front, first-run steps, backups, updates and rollback. For the basics and the
meaning of every setting, see [SELF_HOSTING.md](../SELF_HOSTING.md) and
[`backend/.env.example`](../backend/.env.example).

## What runs

`docker-compose.prod.yml` runs five containers: `postgres`, `redis`, `backend` (Django + gunicorn;
runs `migrate` and `collectstatic` on every start), `worker` (Huey: scheduled library scans and
cover-art scraping) and `web` (nginx: the React app and a proxy to the backend). Only `web`
publishes a port (`BIRDROMS_HTTP_PORT`, default 8080).

The ROM library is the single source of truth. The backend scans it in place every 15 minutes
(`LIBRARY_SCAN_CRONTAB`), uploads are written into it, and scraped cover art is saved next to the
ROMs (`LIBRARY_WRITE_COVERS`). birdROMs never deletes, moves or renames files in the library.

## 1. Images

The GitHub Actions workflow [`docker-publish.yml`](../.github/workflows/docker-publish.yml)
publishes two linux/amd64 images to GHCR on every push to `main` and on `vX.Y.Z` tags:

| Image | Tags |
| --- | --- |
| `ghcr.io/<owner>/birdroms-backend` | `latest`, `sha-<7 chars>` (each push to main); `X.Y.Z` and `latest` (tags) |
| `ghcr.io/<owner>/birdroms-web` | same |

Packages of a private repo are private: on the Docker host run `docker login ghcr.io` with a
token that has `read:packages`. Point the compose file at them (shell or repo-root `.env`):

```env
BIRDROMS_BACKEND_IMAGE=ghcr.io/<owner>/birdroms-backend:latest
BIRDROMS_WEB_IMAGE=ghcr.io/<owner>/birdroms-web:latest
```

Pin `sha-...` or `X.Y.Z` tags instead of `latest` if you want rollbacks to be one edit.
Without a registry, `docker compose -f docker-compose.prod.yml up -d --build` builds from a
checkout, and `docker save | ssh host docker load` moves images between machines.

## 2. Configuration

Copy `backend/.env.example` to an env file and set at least:

| Variable | Notes |
| --- | --- |
| `DJANGO_SECRET_KEY` | long random value; the app refuses to start with a placeholder |
| `DJANGO_ALLOWED_HOSTS` | your hostname, e.g. `roms.example.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://roms.example.com` |
| `DJANGO_BEHIND_HTTPS_PROXY` | `True` when TLS ends at a proxy in front |
| `NUM_PROXIES` | proxies in front of Django: `2` when a TLS proxy sits in front of the bundled `web` nginx |
| `POSTGRES_PASSWORD` (+ `POSTGRES_DB`, `POSTGRES_USER`) | strong password |
| `AUTH_METHODS` | see [Sign-in](#6-sign-in) |
| `MAX_ROM_UPLOAD_BYTES` | and `NGINX_CLIENT_MAX_BODY_SIZE` (compose-level) at least as large; also raise your proxy's limit |

`DJANGO_DEBUG`, `POSTGRES_HOST`, `MEDIA_ROOT`, `LIBRARY_ROOT` and `REDIS_URL` are fixed by the
compose file. Point Compose at the env file with `BIRDROMS_ENV_FILE`. Keep it private (mode 600)
and out of git. The postgres container reads the same file, so every variable in it is visible
inside that container.

## 3. The library

### NFS

Add [`docker-compose.nfs.yml`](../docker-compose.nfs.yml):

```bash
export BIRDROMS_NFS_ADDR=192.168.1.20 BIRDROMS_NFS_EXPORT=/srv/roms   # or put these in .env
docker compose -f docker-compose.prod.yml -f docker-compose.nfs.yml up -d
```

The export path is the folder that contains `ROMS/` (or `Roms/`), or the system folders
themselves. The host needs an NFS client (`apt install nfs-common`) and must be allowed by the
export. If the first start fails with `mount: ... No such file or directory`, the export path
is wrong; with `access denied`, the server's export list does not include this host. Try
`BIRDROMS_NFS_OPTS=rw,nfsvers=3,nolock,hard,noatime` if NFSv4 is not enabled. Mount options are
fixed when the volume is created: to change them run `docker compose down`, then
`docker volume rm <project>_birdroms_library`, then start again.

**Write access.** The app runs as `PUID`:`PGID` (default 568:568, TrueNAS's `apps` account; set
them in `backend/.env`, or use compose `user:`) and must be able to create files in the library
(uploads, covers). The entrypoint never changes the library's ownership. Check it before the first start, with the share mounted:

```bash
docker run --rm -u 568:568 -v <project>_birdroms_library:/library alpine \
  sh -c 'touch /library/.write-test && rm /library/.write-test && echo writable'
```

If it is not writable, either change the export (squash all clients to uid/gid 568, e.g.
`all_squash,anonuid=568,anongid=568`), `chown`/`chmod` the folders on the server, or run read-only
with `LIBRARY_READ_ONLY=true` (uploads and cover write-back are then off). A stale-mount NAS
outage cannot make birdROMs mark everything missing: a scan that would hide more than 25% of the
known ROMs aborts (see [Scans](#5-first-scan)).

### S3

Set `STORAGE_BACKEND=s3` and the `S3_*` variables (see `.env.example`), and
`LIBRARY_S3_PREFIX` to keep the library apart from other bucket content. No NFS file is needed.
See [upgrading-to-the-library.md](upgrading-to-the-library.md).

### Local volume

The default `birdroms_library` volume works without any override; put ROMs in it with the upload
page or by copying into the volume.

## 4. Reverse proxy and TLS

The `web` container speaks HTTP. Put a TLS-terminating proxy in front and forward to
`http://<docker-host>:<BIRDROMS_HTTP_PORT>` with `Host`, `X-Forwarded-For` and
`X-Forwarded-Proto` set. Raise its request body limit to `MAX_ROM_UPLOAD_BYTES`, set generous
read/send timeouts, and turn response buffering off so big ROM downloads stream.

nginx:

```nginx
client_max_body_size 8g;
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

Django builds absolute URLs (OIDC redirects, links baked into downloads) from the `Host` header and
`X-Forwarded-Proto`, so the proxy **must** forward the public `Host` unchanged (`proxy_set_header
Host $host`, not the upstream's address) and `X-Forwarded-Proto https`. The bundled `web` nginx
passes both through. On the Django side that needs the public name in `DJANGO_ALLOWED_HOSTS` and
`DJANGO_CSRF_TRUSTED_ORIGINS`, and `DJANGO_BEHIND_HTTPS_PROXY=True` (it trusts
`X-Forwarded-Proto`, so `request.build_absolute_uri("/")` is `https://<host>/`).
`USE_X_FORWARDED_HOST` is deliberately not used: the real `Host` header already arrives intact.
A wrong value shows up as `http://` links, a 400 (host not allowed) or CSRF failures.

Do not put browser-only forward-auth (Authelia/Authentik proxy auth, basic auth) in front of
`/api/`: the handheld client and other API users send `Authorization` headers and cannot answer
a login redirect. Use birdROMs' own sign-in instead (next section). Gating `/admin/` is fine.

## 5. First run

```bash
docker compose -f docker-compose.prod.yml pull                  # skip when building locally
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps                    # backend and web become healthy
docker compose -f docker-compose.prod.yml logs -f backend       # migrations ran on start
```

Create the first admin (a Django superuser has the `super_admin` role and can use `/admin/`):

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

### First scan

The worker scans every 15 minutes. To see the result immediately:

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py scan_library
```

It prints `added`, `changed`, `missing`, `restored` and `unknown folders`, and exits 1 if the scan
aborts. A first scan only adds. Use `--accept-removals` only when a scan aborted with the
safety-guard message ("would mark more than 25% of known ROMs missing") **and** you have
confirmed the library is mounted and the removals are real (for example after deliberately
reorganising the share). Never use it to silence an unmounted share. The same action is the
**Accept removals** button on the Library page.

Cover art for ROMs without one is scraped in the background (and re-queued hourly). On a big
library that means many requests to the cover providers and, with `LIBRARY_WRITE_COVERS=True`,
many new PNGs in the library's `Imgs/` folders. Set `LIBRARY_WRITE_COVERS=False` (or
`COVER_ART_PROVIDERS=`) first if you want to hold that back.

## 6. Sign-in

- `AUTH_METHODS=local` (the default) also enables **self-registration**: anyone who can reach the
  site can create a read-only account and download every ROM. Do not use it on a site reachable
  from the internet unless that is what you want.
- `AUTH_METHODS=oidc` with `ALLOW_LOCAL_LOGIN=False` hands account control to your identity
  provider (Pocket ID, Authentik, Keycloak, Authelia, Google...). Restrict the client to the
  group of people who should have access at the provider. Members of `OIDC_ADMIN_GROUP` become
  `super_admin`; everyone else is read-only. Keep one Django superuser (created above) for
  `/admin/`. Callback URL: `https://<host>/api/auth/oidc/callback/`.

## 7. Smoke test

1. `docker compose -f docker-compose.prod.yml config -q` parses.
2. `curl -s https://<host>/api/auth/config/` returns the enabled methods.
3. The UI loads, and `https://<host>/admin/` is styled (static files work).
4. Sign in and upload a small ROM: it appears in the library and downloads byte-identical. On a
   filesystem library it is a new file under `ROMS/<SYSTEM>/` on the share.
5. `docker compose ... logs worker` shows Huey running; covers appear within a minute.

## 8. Backups

- **Database** (library entries, users, playlists, device tokens):

  ```bash
  docker compose -f docker-compose.prod.yml exec -T postgres \
    sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > birdroms-$(date +%F).dump
  ```

  Run it nightly from cron and keep a few weeks. Restore:
  `pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < file.dump` inside the
  postgres container, with the backend and worker stopped.
- **The library** is your ROMs; back it up with the storage system it lives on (NAS snapshots,
  bucket versioning). birdROMs does not need a copy: a lost database is rebuilt by rescanning,
  except users, playlists and device pairings.
- **The env file** holds your secrets; keep a copy somewhere private.

## 9. Updating and rolling back

```bash
docker compose -f docker-compose.prod.yml exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > pre-update.dump   # 1. back up
docker compose -f docker-compose.prod.yml images > images-before.txt                  # 2. note versions
docker compose -f docker-compose.prod.yml pull                                        # 3. new images
docker compose -f docker-compose.prod.yml up -d                                       # 4. migrates on start
docker compose -f docker-compose.prod.yml ps                                          # 5. healthy?
```

To roll back, set the image variables to the previous `sha-...`/`X.Y.Z` tag and run `up -d`
again. If the new version applied database migrations the old one cannot read, restore
`pre-update.dump` after rolling the images back.
