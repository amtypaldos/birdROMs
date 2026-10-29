# birdROMs

[![CI](https://github.com/amtypaldos/birdROMs/actions/workflows/ci.yml/badge.svg)](https://github.com/amtypaldos/birdROMs/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**birdROMs is a self-hosted place to keep your retro game library and share it with a small group of friends.**
Point it at a folder (or S3 bucket) of ROMs laid out the way muOS handheld firmware expects, and your
friends can browse it with cover art in the browser or on a handheld, and download what they want.
Everything runs on your own hardware; there is no central service.

It is a Django + React web app with an optional on-device client for muOS handhelds
([birdroms-handheld](https://github.com/amtypaldos/birdroms-handheld)).

<!-- TODO: add screenshots here (library grid, playlist, Handheld page). Put the images under docs/images/. -->

> **ROMs and copyright.** birdROMs does not include, ship or distribute any ROMs, BIOS files or
> other copyrighted game content. It is a tool for managing files you already have. You are
> responsible for only storing and sharing content you have the right to use and share (for example
> homebrew, your own dumps where that is lawful where you live, or content you are licensed to
> distribute). The project and its contributors accept no responsibility for what you host.

## Features

- **Library you already have.** Reads a muOS-style tree (`ROMS/<SYSTEM>/<game file>`, box art in
  `ROMS/<SYSTEM>/Imgs/`) from a folder, an NFS share or an S3-compatible bucket, in place. A scan runs
  every 15 minutes and indexes what it finds. birdROMs never deletes, moves, renames or overwrites
  files in your library.
- **Uploads.** Signed-in users can upload ROMs from the browser; files are written into the library
  under the right system folder (`ROMS/SFC/...`) and keep their original file name.
- **Clean titles, original file names.** Names like `Super Mario World (USA) [!].sfc` are shown as a
  clean title with region/dump tags, but downloads always keep the original file name, so saves,
  save states and box art on your devices stay linked to the game.
- **Platform detection** from folder names and file extensions (dozens of systems).
- **Cover art.** Uses the box art already in your library, and scrapes missing art from
  libretro-thumbnails and ScreenScraper in the background.
- **Playlists** to group games for friends.
- **Sign-in** with local accounts, single sign-on (OIDC: Pocket ID, Authentik, Keycloak, Authelia,
  Google, ...), or both.
- **Handheld client.** A muOS app that pairs with a QR code and downloads playlists and platforms
  straight onto the device. The server hosts the app package for friends to download.
- **Installable web app (PWA)** (needs HTTPS).
- **Private by default.** Nothing is public: every download goes through a permission-checked API,
  even when the files sit in S3.

Out of scope: online play, netplay and save-state sync. (To sync saves across your own devices, use
something like Syncthing.)

## Quick start (Docker)

You need Docker Engine 24+ with Compose v2.24+, and a few GB of disk for your library.

```bash
git clone https://github.com/amtypaldos/birdROMs.git && cd birdROMs
cp backend/.env.example backend/.env
# edit backend/.env: DJANGO_SECRET_KEY, DJANGO_DEBUG=False, DJANGO_ALLOWED_HOSTS,
# DJANGO_CSRF_TRUSTED_ORIGINS and POSTGRES_PASSWORD at least (see SELF_HOSTING.md)

# Use the prebuilt multi-arch images (amd64 + arm64) ...
export BIRDROMS_BACKEND_IMAGE=ghcr.io/amtypaldos/birdroms-backend:latest
export BIRDROMS_WEB_IMAGE=ghcr.io/amtypaldos/birdroms-web:latest
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
# ... or build them yourself: docker compose -f docker-compose.prod.yml up -d --build

docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

birdROMs is now on `http://<host>:8080`. Sign in with that account (a Django superuser is a
`super_admin`). The stack is PostgreSQL, Redis, gunicorn, a background worker (library scans and
cover-art scraping) and nginx serving the UI. By default the library is an empty Docker volume:
upload ROMs in the web UI, or point birdROMs at an existing library (a host folder, an NFS share, or
S3) as described in [docs/deploying.md](docs/deploying.md#3-the-library).

**Read [SELF_HOSTING.md](SELF_HOSTING.md) before exposing it to the internet.**

## Documentation

| Doc | What it covers |
| --- | --- |
| [SELF_HOSTING.md](SELF_HOSTING.md) | Step-by-step setup: configuration, HTTPS, single sign-on, storage, backups, troubleshooting |
| [docs/deploying.md](docs/deploying.md) | Production runbook: prebuilt images, NFS/S3 library, reverse proxy, first scan, updates and rollback |
| [docs/upgrading-to-the-library.md](docs/upgrading-to-the-library.md) | Upgrading from the older upload-only storage to the ROM library |
| [docs/handheld-app.md](docs/handheld-app.md) | Publishing the muOS handheld app so friends can download it from your server |
| [backend/.env.example](backend/.env.example) | Every setting, with comments |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup, tests, pull request expectations |
| [SECURITY.md](SECURITY.md) | How to report a vulnerability |

The rest of this README is the reference for sign-in, ROM handling and the API.

## The handheld app

The muOS client lives in its own repository, [birdroms-handheld](https://github.com/amtypaldos/birdroms-handheld).
Build it there (`just package`) or take `birdROMs.muxapp` from its GitHub Releases, then publish it on your
server with `python manage.py publish_handheld` ([docs/handheld-app.md](docs/handheld-app.md)). Signed-in
users get a **Handheld** page with install steps and a download that already knows your server's address.
On the device, pair with the QR code, pick playlists or platforms and press Start to download. Device
tokens are read-only and can be revoked.

## Development

Contributors can run the whole stack with Docker or run everything natively. Full instructions,
including tests and lint, are in [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
docker compose up --build        # Postgres + Django (runserver) + Vite, hot reload
# Django API on http://localhost:8000, UI on http://localhost:5173
docker compose exec backend python manage.py createsuperuser
```

The dev stack mounts `./library` (override with `LIBRARY_PATH`) as the ROM library; create the folder first.

## Tech stack

- Backend: Django 5, Django REST Framework, PostgreSQL, [Huey](https://huey.readthedocs.io/) + Redis for background tasks
- Frontend: React 18 + Vite 5
- Auth: Django auth with token-based API auth; local login and/or OIDC SSO ([Authlib](https://docs.authlib.org/))
- Storage: local/NFS filesystem or any S3-compatible object store
- Images: Docker, published to GHCR for linux/amd64 and linux/arm64

Project layout: `backend/` (Django API), `frontend/` (React client), `docs/`, `scripts/`.

### Continuous integration

GitHub Actions ([`ci.yml`](.github/workflows/ci.yml)) runs on every push and pull request:

- **Backend**: `uv sync --locked`, `uv run python manage.py test` (Python 3.12, Postgres service container).
- **Frontend**: `yarn install --immutable`, `yarn lint`, `yarn test`, `yarn build` (Node 24, Yarn via corepack).
- **Docker**: builds both production images for `linux/amd64` and `linux/arm64` (the latter under QEMU),
  checks the `PUID`/`PGID` behaviour of the backend image and validates the compose files.

[`docker-publish.yml`](.github/workflows/docker-publish.yml) publishes the images to GHCR on pushes to
`main` (`latest`, `sha-<7>`) and on `vX.Y.Z` tags (`X.Y.Z`, `latest`), and creates a GitHub Release for tags.

## Auth and Roles

Roles are implemented as user groups:

- `super_admin`: everything below, plus editing and deleting ROM entries, re-scraping cover art and
  administering the library (status, rescans, accepting removals)
- `readonly`: list ROMs, download files, use playlists and pair a handheld

For a trusted friend group, uploading a ROM and creating playlists are open to every signed-in
user. Fine-grained roles are not implemented yet; see `backend/apps/roms/permissions.py` to
tighten uploads. Only a playlist's creator can change it. Deleting a ROM entry removes it from
birdROMs only, never the file from your library.

Use Django admin to assign roles to local users. SSO users get their role from the provider
(see below).

### Login methods

`AUTH_METHODS` (comma-separated, order does not matter) picks the login methods. The web UI
asks the public `GET /api/auth/config/` endpoint which methods are on and shows only those.

| Setup | Env |
| --- | --- |
| Local only (default) | `AUTH_METHODS=local` |
| SSO only | `AUTH_METHODS=oidc`, `ALLOW_LOCAL_LOGIN=False` |
| Both | `AUTH_METHODS=local,oidc` |

- **local**: `POST /api/auth/login/` and `POST /api/auth/register/` (self-registered users are
  `readonly`). `ALLOW_LOCAL_LOGIN` force-enables them and defaults to `DJANGO_DEBUG`, so local
  dev always works. When local login is off, both endpoints return 404.
- **oidc**: standard Authorization Code flow with PKCE against a single OpenID Connect
  provider. It uses [Authlib](https://docs.authlib.org/), a maintained library that handles
  discovery, state/nonce, and ID token signature checks. The browser goes to
  `/api/auth/oidc/login/`, signs in at the provider, and comes back to
  `/api/auth/oidc/callback/`. The callback then redirects to the UI (`OIDC_LOGIN_REDIRECT_URL`)
  with the API token in the URL fragment, and the UI removes it from the address bar right away.

Both methods issue the same DRF API token, so the rest of the API works the same either way.
`GET /api/auth/me/` returns the signed-in user's `id`, `username`, `email` and `role`.

On first SSO login, birdROMs creates a user linked to the provider's stable `sub` and gives
them a role from the `OIDC_GROUPS_CLAIM` claim. Members of `OIDC_ADMIN_GROUP` get
`super_admin` and everyone else gets `readonly`. The role is re-synced on every SSO login.
Returning users are matched on `sub`, never on username. Matching existing local accounts by
email is opt-in (`OIDC_LINK_BY_EMAIL=True`) and only applies to emails the provider marks as
verified.

**Pocket ID (reference):** create an OIDC client with callback URL
`https://roms.example.com/api/auth/oidc/callback/`, then:

```env
AUTH_METHODS=oidc
ALLOW_LOCAL_LOGIN=False
OIDC_ISSUER=https://id.example.com
OIDC_CLIENT_ID=<client id>
OIDC_CLIENT_SECRET=<client secret>
OIDC_REDIRECT_URI=https://roms.example.com/api/auth/oidc/callback/
OIDC_LOGIN_REDIRECT_URL=https://roms.example.com/
OIDC_ADMIN_GROUP=birdroms-admins
OIDC_PROVIDER_NAME=Pocket ID
```

**Authentik:** create an OAuth2/OpenID provider and application (slug `birdroms`). Authentik
sends `groups` in the default `profile` scope:

```env
OIDC_ISSUER=https://authentik.example.com/application/o/birdroms
OIDC_SCOPES=openid email profile
OIDC_ADMIN_GROUP=birdroms-admins
OIDC_PROVIDER_NAME=Authentik
```

**Keycloak:** use `OIDC_ISSUER=https://keycloak.example.com/realms/<realm>` and add a "Group
Membership" mapper (claim name `groups`, full group path off) to the client.
**Google:** use `OIDC_ISSUER=https://accounts.google.com` and `OIDC_SCOPES=openid email profile`.
Google has no groups claim, so every Google user is `readonly`. Promote users in Django admin
instead. That role then gets reset on their next SSO login unless they are a Django superuser.

Every variable is documented in `backend/.env.example`. SAML is not supported.

## ROM Classification

Uploads are classified server-side from the file's final extension
(case-insensitive, so `Super.Mario.World.SFC` is SNES). If an upload leaves `platform` blank it
is filled in automatically; if `platform` is provided (on upload or later via `PATCH`) that
value is kept as-is, so ambiguous files can be corrected manually. Unrecognized extensions are
tagged as `unknown`.

The canonical map is `EXTENSION_TO_PLATFORM` in `backend/apps/roms/services.py`
(`SUPPORTED_EXTENSIONS` and `SUPPORTED_PLATFORMS` are derived from it). When a library scan finds a
game, the platform comes from the system folder it sits in (`ROMS/SFC/` is SNES; the folder and alias
table is `backend/apps/roms/data/platform_aliases.csv`), and the extension decides inside shared
folders. Uploads without a platform are classified by extension and written to the matching muOS
system folder; unknown platforms go to `ROMS/_UNSORTED`.

| Platform | Extensions |
| --- | --- |
| NES | `.nes` |
| SNES | `.sfc`, `.smc` |
| Nintendo 64 | `.n64`, `.z64`, `.v64` |
| Nintendo GameCube | `.gcm`, `.rvz`, `.gcz` |
| Nintendo Wii | `.wbfs` |
| Game Boy | `.gb` |
| Game Boy Color | `.gbc` |
| Game Boy Advance | `.gba` |
| Nintendo DS | `.nds` |
| Nintendo 3DS | `.3ds`, `.cia` |
| Sega Master System | `.sms` |
| Sega Genesis | `.gen`, `.md`, `.smd` |
| Sega Game Gear | `.gg` |
| Sega 32X | `.32x` |
| Sega Dreamcast | `.gdi`, `.cdi` |
| Sony PlayStation | `.pbp` |
| Sony PSP | `.cso` |
| PC Engine / TurboGrafx-16 | `.pce` |
| Neo Geo Pocket | `.ngp` |
| Neo Geo Pocket Color | `.ngc` |
| WonderSwan | `.ws` |
| WonderSwan Color | `.wsc` |
| Atari 2600 | `.a26` |
| Atari 7800 | `.a78` |
| Atari Lynx | `.lnx` |
| Atari Jaguar | `.jag`, `.j64` |
| Disc Image (generic) | `.iso`, `.bin`, `.cue`, `.chd` |
| Archive (generic) | `.zip`, `.7z` |

Disc images are shared by many systems (Saturn, Sega CD, PlayStation, PS2, PSP, …), so they get
the generic "Disc Image" label — set `platform` explicitly (e.g. `Sega Saturn`, `Sony
PlayStation 2`) when uploading them.

## Upload Validation

Uploads are treated as untrusted. `POST /api/roms/` writes the file into the library (see below) and
returns `400` with an error on the `file` field when:

- the extension (checked case-insensitively) is not in the table above. That table is the
  complete allowlist and includes `.zip`/`.7z` archives. Files with no extension are rejected too.
- the file is empty (0 bytes).
- the file is larger than `MAX_ROM_UPLOAD_BYTES`, which defaults to `2147483648` (2 GiB) and can
  be set in the environment. If a reverse proxy sits in front of the app, raise its body-size
  limit to match (with the bundled nginx, `NGINX_CLIENT_MAX_BODY_SIZE`).
- a file with the same name is already in that system folder (uploads never overwrite), or the
  library is read-only (`LIBRARY_READ_ONLY=true`) or unreachable.

## Library and file storage

**The ROM library** is where games live. It is a muOS-layout tree, `ROMS/<SYSTEM>/<file>` with box
art in `ROMS/<SYSTEM>/Imgs/<name>.png`, on one of:

- `filesystem` (default): the folder `LIBRARY_ROOT` (`/library` in Docker; an NFS mount works
  like any folder);
- `s3`: an S3-compatible bucket (AWS S3, MinIO, Cloudflare R2, Backblaze B2), optionally under
  `LIBRARY_S3_PREFIX`.

`LIBRARY_BACKEND` picks one and defaults to the value of `STORAGE_BACKEND`. A scan runs every 15 minutes
(`LIBRARY_SCAN_CRONTAB`, needs the worker), or on demand with `python manage.py scan_library` or the
**Library** page for `super_admin`s. A scan adds new files, updates changed ones and marks vanished files
as missing (hidden, not deleted). If a scan would hide more than 25% of the known ROMs it aborts, so an
unmounted share can't empty your library; see [docs/deploying.md](docs/deploying.md#first-scan).
Uploads are written into the library; scraped cover art is saved next to the ROMs unless
`LIBRARY_WRITE_COVERS=False`. Set `LIBRARY_READ_ONLY=true` and birdROMs never writes there at all.

**Media storage** (`MEDIA_ROOT`, or the same S3 bucket) holds the rest: scraped cover art and the
published handheld package. Choose it with `STORAGE_BACKEND`:

- `filesystem` (default): files live under `MEDIA_ROOT`, which defaults to `backend/media`.
- `s3`: configured with `S3_BUCKET_NAME`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_ENDPOINT_URL`,
  `S3_REGION`, `S3_CUSTOM_DOMAIN`, `S3_PATH_STYLE` (MinIO usually needs `True`), `S3_LOCATION` and
  `S3_QUERYSTRING_AUTH`. Objects are never made public, and file URLs are signed by default.

Every variable is documented in `backend/.env.example`.

## Browsing the library

`GET /api/roms/` is paginated and returns `{count, next, previous, results}`, 24 ROMs per page
by default. Use `?page=N` to move between pages and `?page_size=N` to change the size (max 100).
A page past the end returns 404. Filters:

- `?search=zelda` matches part of the title or the original file name, ignoring case.
- `?platform=NES` matches the platform exactly (use the names from the platform table).

You can combine filters and pagination, for example `?search=zelda&platform=Game+Boy+Advance&page=2`.
`GET /api/roms/platforms/` lists the platforms that have at least one ROM, sorted by name. The web UI
uses it for the platform dropdown. Both endpoints need a `readonly` or `super_admin` user.

## Downloads

ROMs are private. Django never serves `MEDIA_ROOT` or the library directly, and the API does not return a
storage URL for the file. Downloads go through `GET /api/roms/{id}/download/`, which needs a signed-in
`readonly` or `super_admin` user (or a paired device token) and returns the file as an attachment whose
`Content-Disposition` filename is the **original file name** (for example `Super Mario World (USA).sfc`),
not the cleaned-up title: muOS and RetroArch key saves, states and box art to the ROM's file name.
Unknown ids return 404. This works the same way with both storage backends: birdROMs streams the file
from storage through the app and never redirects to a pre-signed S3 URL, so clients never get a direct
storage URL. Each ROM in the API lists this endpoint as `download_url`. The web UI fetches it with the
user's token and saves the response as a blob.

## Cover Art Scraping

Games whose library folder already has box art (`ROMS/<SYSTEM>/Imgs/<name>.png`) use it. For the rest,
a background task (queued on upload and found again by an hourly sweep, so it needs the `worker`) looks
up cover art and saves the image to the media storage under `covers/`, and also next to the ROM in the
library's `Imgs/` folder when the library is writable (`LIBRARY_WRITE_COVERS`), where muOS devices
find it too. It is a real stored file, not a link to the provider, so the library keeps working offline. `cover_art_source` records which
provider supplied the image.

Providers are tried in the order set by `COVER_ART_PROVIDERS` until one returns an image:

| Provider | Credentials | How it matches |
| --- | --- | --- |
| `libretro` | none | Maps the platform to a [libretro-thumbnails](https://thumbnails.libretro.com/) system and tries the ROM title, then the uploaded file name (No-Intro names such as `Super Mario World (USA)` match best). It looks for boxart first, then the title screen, then a snapshot. |
| `screenscraper` | `SS_DEV_ID`, `SS_DEV_PASSWORD` (+ optional `SS_USER`, `SS_PASSWORD`) | Queries [ScreenScraper](https://www.screenscraper.fr/) by file name and system and picks the 2D box art (then title screen or screenshot). It is skipped when no developer credentials are set. |

Every HTTP call uses the `COVER_ART_TIMEOUT` (seconds, default 10). Only image responses up to
10 MB are accepted. Scraping never fails an upload or a scan: provider errors are logged and the ROM is
saved without art. Set `COVER_ART_PROVIDERS=` (empty) to turn scraping off.

- `POST /api/roms/{id}/scrape_cover/` (super_admin) re-scrapes and replaces the art. It returns
  404 when nothing matched.
- `GET /api/roms/{id}/cover/` serves the stored image. It is permission-checked like downloads,
  and the ROM's `cover_art_url` points at it (`null` when there is no art).
- `uv run python manage.py backfill_cover_art` fetches art for existing ROMs that have none.
  Add `--force` to re-scrape every ROM.

## License

birdROMs is released under the [MIT License](LICENSE). The bundled web fonts (Chakra Petch and
Press Start 2P) are under the SIL Open Font License 1.1; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
for third-party licenses.

birdROMs does not ship or distribute any ROMs, BIOS files or copyrighted game content. You are
responsible for making sure that anything you add to your instance is content you have the right to
use and share. See also [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) and [SECURITY.md](SECURITY.md).
