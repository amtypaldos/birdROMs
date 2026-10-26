# birdROMs

`birdROMs` is a Django + React web app for private retro ROM sharing and management with role-based access, extension-based ROM classification, and cover art scraping support.

## Self-hosting / Open source

birdROMs is free and open-source software. There is no central service: anyone can run
their own private instance for themselves and a trusted group. Every deployment-specific
value (database, secret key, allowed hosts, auth and storage settings) is configured
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
- Auth: Django auth + token-based API auth; local login and/or OIDC SSO (Authlib)
- Storage: local/NFS filesystem by default (`MEDIA_ROOT`), or any S3-compatible object store (`STORAGE_BACKEND=s3`)

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

ROM classification is determined server-side from the file's final extension
(case-insensitive, so `Super.Mario.World.SFC` is SNES). If an upload leaves `platform` blank it
is filled in automatically; if `platform` is provided — on upload or later via `PATCH` — that
value is kept as-is, so ambiguous files can be corrected manually. Unrecognized extensions are
tagged as `unknown`.

The canonical map is `EXTENSION_TO_PLATFORM` in `backend/apps/roms/services.py`
(`SUPPORTED_EXTENSIONS` and `SUPPORTED_PLATFORMS` are derived from it).

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

Uploads are treated as untrusted. `POST /api/roms/` returns `400` with an error on the `file`
field when:

- the extension (checked case-insensitively) is not in the table above. That table is the
  complete allowlist and includes `.zip`/`.7z` archives. Files with no extension are rejected too.
- the file is empty (0 bytes).
- the file is larger than `MAX_ROM_UPLOAD_BYTES`, which defaults to `2147483648` (2 GiB) and can
  be set in the environment. If a reverse proxy sits in front of the app, raise its body-size
  limit to match.

## File Storage

ROM files and cover art go to Django's default storage. You choose the backend with
`STORAGE_BACKEND`, so switching needs no code changes:

- `filesystem` (default): files live under `MEDIA_ROOT`, which defaults to `backend/media`. For
  NFS, mount the share and set `MEDIA_ROOT` to the mount path.
- `s3`: any S3-compatible store (AWS S3, MinIO, Cloudflare R2, Backblaze B2), configured with
  `S3_BUCKET_NAME`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_ENDPOINT_URL`, `S3_REGION`,
  `S3_CUSTOM_DOMAIN`, `S3_PATH_STYLE` (MinIO usually needs `True`), `S3_LOCATION` and
  `S3_QUERYSTRING_AUTH`. Objects are never made public, and file URLs are signed by default.

Every variable is documented in `backend/.env.example`.

## Browsing the library

`GET /api/roms/` is paginated and returns `{count, next, previous, results}`, 24 ROMs per page
by default. Use `?page=N` to move between pages and `?page_size=N` to change the size (max 100).
A page past the end returns 404. Filters:

- `?search=zelda` matches part of the title, ignoring case.
- `?platform=NES` matches the platform exactly (use the names from the platform table).

You can combine filters and pagination, for example `?search=zelda&platform=Game+Boy+Advance&page=2`.
`GET /api/roms/platforms/` lists the platforms that have at least one ROM, sorted by name. The web UI
uses it for the platform dropdown. Both endpoints need a `readonly` or `super_admin` user.

## Downloads

ROMs are private. Django never serves `MEDIA_ROOT` directly, and the API does not return a
storage URL for the file. Downloads go through `GET /api/roms/{id}/download/`, which needs an
authenticated `readonly` or `super_admin` user and returns the file as an attachment
(`Content-Disposition: attachment; filename="<title><ext>"`). Unknown ids return 404. This works
the same way with both storage backends. birdROMs streams the file from storage through the app
and never redirects to a pre-signed S3 URL, so clients never get a direct storage URL. Each ROM
in the API lists this endpoint as `download_url`. The web UI fetches it with the user's token
and saves the response as a blob.

## Cover Art Scraping

`POST /api/roms/{id}/scrape-cover/` attempts to fetch cover art metadata based on ROM title/platform. The initial implementation provides a service hook and safe fallback, ready for integration with providers such as IGDB, ScreenScraper, or custom scrapers.

## License

birdROMs is released under the [MIT License](LICENSE).

birdROMs does not ship or distribute any ROMs. You are responsible for ensuring that any
files you upload to your instance are ones you have the right to use and share.
