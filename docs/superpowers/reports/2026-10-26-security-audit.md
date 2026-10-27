# birdROMs security audit (backend-polish round)

Date: 2026-10-26. Scope: the code added or changed in the backend-polish round plus the
previously unreviewed baseline (`frontend/src/App.jsx`, `frontend/src/api/client.js`,
`frontend/vite.config.js`, `backend/pyproject.toml`). Method: read the code for the real attack
surface (auth, upload, download/access control, scraper SSRF, storage/secrets/settings,
frontend, dependencies, deploy files). Tools-based scanners were not run; this is a manual review.

Status key: **Fixed** (code change plus regression test in this round), **Documented**
(accepted/by design, noted), **Follow-up** (real, deliberately left for a separate change).

## Findings

| # | Area | Severity | Finding | Status |
|---|------|----------|---------|--------|
| 1 | Settings | High | `DJANGO_DEBUG` defaulted to **True** when unset, and `.env.example` ships `DJANGO_DEBUG=True` / `DJANGO_SECRET_KEY=change-me`. `cp .env.example .env` on a production host left debug pages on and, because the secret-key check is skipped under DEBUG, a placeholder signing key. Debug also turns on local login and inline task execution. | Fixed |
| 2 | Scraper | High | ScreenScraper credentials (`devid`, `devpassword`, `ssid`, `sspassword`) are sent as query parameters, and `requests` exception messages quote the full URL. The warnings in `scrape_cover_art` / `ScreenScraperGame` logged `exc` verbatim, writing the developer password and the user's password to the logs. | Fixed |
| 3 | Scraper / SSRF | High | `download_image` fetched any URL found in the ScreenScraper `medias` payload with `requests.get` (redirects followed by default). A malicious or compromised response (or a hostile redirect) could make the server request internal addresses (cloud metadata, `localhost`, the Docker network) or plain HTTP. libretro URLs were already built on a fixed host, but their redirects were also unchecked. | Fixed |
| 4 | Auth | High (opt-in) | Account pre-hijack via `OIDC_LINK_BY_EMAIL`: local registration never verifies email, so an attacker can register `victim@...` locally, keep the password and API token, and when the victim later signs in via SSO the first-login email link attached the victim's identity to the attacker's account. | Fixed |
| 5 | Auth | Medium | No throttling on `/api/auth/login/` (password guessing) or `/api/auth/register/`. | Fixed |
| 6 | Auth | Medium | Registration enforced only `min_length=8`, bypassing `AUTH_PASSWORD_VALIDATORS` (common, numeric, similar-to-username). | Fixed |
| 7 | Download | Low | A ROM title containing CR/LF flowed into `Content-Disposition` (header-injection class; Django's header validation should reject it, but the download name is now sanitized rather than relying on that). Control characters are stripped from the filename. | Fixed |
| 8 | Dependencies | Low | `djangorestframework-simplejwt` was declared but unused (and pulled in `pyjwt`). Removed from `pyproject.toml`, `requirements.txt`, `uv.lock`. | Fixed |
| 9 | Frontend / dev | Low | Vite dev proxy still forwarded `/media`, which the backend deliberately never serves. Removed. | Fixed |
| 10 | Deploy | Low | `docker-compose.prod.yml` now pins `DJANGO_DEBUG=False` so a copied example `.env` cannot enable debug in the production stack (defence in depth with #1). | Fixed |
| 11 | Auth / policy | Medium | With the default `AUTH_METHODS=local`, **anyone who can reach the server can self-register and receive the `readonly` role, which can list and download every ROM**. This is documented behaviour, but for a "private" library it is a risky default. Recommend an `ALLOW_REGISTRATION` flag (default off in production) or admin approval. Left as a product decision. | Follow-up |
| 12 | Auth | Medium | API tokens (DRF `Token`) never expire, rotate, or get revoked: there is no logout endpoint (the SPA only clears `localStorage`), and SSO logins reuse the same token via `get_or_create`. A leaked token is valid until the user is deleted. Needs a design (expiring tokens or JWT, logout endpoint, per-session tokens). | Follow-up |
| 13 | Auth | Medium | Any user the IdP authenticates gets `readonly` access. If the IdP allows open sign-up (e.g. Google), that is everyone. Recommend `OIDC_ALLOWED_GROUP` / `OIDC_ALLOWED_EMAIL_DOMAINS`. | Follow-up |
| 14 | Frontend | Medium | The API token is stored in `localStorage` (`birdroms_token`), so any future XSS exfiltrates it. No XSS sink exists today (no `dangerouslySetInnerHTML`, `innerHTML`, `eval`; server strings are rendered as React text; cover art/ROMs are blobs). An HttpOnly cookie session would remove the risk but is a larger auth redesign. | Follow-up |
| 15 | Auth | Low | `RegisterThrottle` keys on DRF's client ident, which behind a proxy needs `REST_FRAMEWORK["NUM_PROXIES"]` set to be accurate (otherwise it is the proxy address, or a spoofable `X-Forwarded-For`). The login throttle is keyed per username precisely to avoid this. Throttle counters use the default per-process cache, so each gunicorn worker counts separately. Consider a shared cache (the Redis already used by Huey). | Follow-up |
| 16 | Auth | Low | `/admin/` still accepts username/password for staff users even when local login is disabled (SSO-only setups). Superusers created with `createsuperuser` are the intended break-glass path; document it or restrict admin to SSO. | Documented |
| 17 | Auth | Low | `oidc_error` (the `error_description` from the provider's redirect) is reflected into the URL fragment and shown in the SPA: text-only (React escapes it), but it allows message spoofing via a crafted callback link. | Follow-up |
| 18 | Upload | Low | The size cap is enforced in the serializer after the body is received, so a client can make the server spool up to the proxy limit to a temp file before a 400. The nginx `client_max_body_size` (tied to `MAX_ROM_UPLOAD_BYTES` in the compose file) bounds this. Content is classified by extension only (no magic-byte sniffing); files are never executed or extracted, and downloads are `attachment`. | Documented |
| 19 | Deploy | Low | Dev `docker-compose.yml` publishes Postgres on all interfaces with the well-known `birdroms` password; `.env.example` also suggests `POSTGRES_PASSWORD=birdroms` (prod Postgres is not published, but the weak example password should be changed). Gunicorn runs with `--forwarded-allow-ips=*`, which is acceptable only because the backend port is not published in the prod compose file. | Documented |
| 20 | Logging | Low | With DEBUG-level logging enabled, urllib3 logs request paths including query strings (ScreenScraper credentials). Not enabled anywhere by default. | Documented |

## Checked and found sound

- **OIDC flow**: authlib validates `state`, `nonce` and PKCE (S256) and verifies the ID-token signature and claims; the callback post-login redirect is the operator-set `OIDC_LOGIN_REDIRECT_URL` (no user-controlled redirect, so no open redirect); the token travels in the URL fragment and the SPA strips it from history. Users match on `(issuer, sub)`; email linking is opt-in and requires `email_verified is True`. Roles are re-derived from the verified groups claim on every login (removal at the IdP demotes), superusers are never demoted, and missing groups fail safe to `readonly`. Inactive users receive no token. Local login is hard-gated (404) by `AUTH_METHODS`/`ALLOW_LOCAL_LOGIN`.
- **Access control**: `ROMViewSet` requires a role for every action (`readonly`/`super_admin` read; writes and `scrape_cover` need `super_admin`); `download` and `cover` stream through the app with the same check, `/media/` is not routed, and S3 objects are never made public (`default_acl=None`, signed URLs). Covers get `nosniff` and an image content type chosen from the stored extension, which only the scraper's allowlisted image types can produce. Regression tests now cover anonymous/roleless/readonly access to files, covers and write actions.
- **Upload**: extension allowlist, size cap, empty-file rejection; the storage layer (`get_valid_name`/basename) prevents path traversal via the uploaded filename (now covered by a test with `../`, absolute and backslash names).
- **Scraper**: libretro URLs are built from a fixed base with the title percent-encoded (the characters `/` `\` `?` etc. are replaced), so a ROM title cannot change host or path. Images are capped at 10 MiB, must have an image content type, and now come only from allowlisted HTTPS hosts. The ROM filename is sent to ScreenScraper as `romnom` (a deliberate disclosure of uploaded file names to that service).
- **Admin**: the ROM admin escapes via `format_html`; thumbnails use the authenticated cover endpoint.
- **Secrets**: no secrets are committed (`.env` is git-ignored and `.dockerignore`d; `.env.example` holds placeholders); S3 and ScreenScraper credentials come from the environment only; the production image bakes in no secrets and runs as a non-root user. `ALLOWED_HOSTS` defaults to `localhost`; secure cookies and `X-Forwarded-Proto` trust are opt-in via `DJANGO_BEHIND_HTTPS_PROXY`. CSRF: DRF `TokenAuthentication` is first, and `SessionAuthentication` enforces CSRF for session-authenticated unsafe requests.
- **Frontend**: no XSS sinks; the Vite dev server binds to localhost by default and only proxies `/api`; errors are rendered as text.

## Fix summary (this round)

Code: `birdroms/deploy_config.py` (`parse_debug`), `birdroms/settings.py` (fail-closed DEBUG, throttle rates), `apps/roms/cover_art.py` (`is_allowed_image_url`, manual redirect checks, `redact_secrets`), `apps/roms/views.py` (control characters in filename), `apps/accounts/{throttles,views,serializers,services}.py` (throttles, password validators, link takeover), deploy/config (`docker-compose.prod.yml`, `.env.example`, `vite.config.js`, `pyproject.toml`, `requirements.txt`, `uv.lock`).

Tests added: `ParseDebugTests`, `ImageUrlAllowlistTests`, `SecretRedactionTests`, `MediaAccessControlTests`, `HostileInputTests`, `LoginThrottleTests`, plus register validator/throttle tests and the squatter-eviction OIDC test.

Behaviour changes worth knowing: (a) `DJANGO_DEBUG` must now be `True` to enable debug (the native-dev `.env` copied from `.env.example` already does); (b) ScreenScraper media URLs that are not HTTPS on `screenscraper.fr` are ignored; (c) with `OIDC_LINK_BY_EMAIL`, the linked account loses its local password and API token; (d) login is limited to 10 attempts/min per username and registration to 10/hour per client address.
