# birdROMs — Backend Polish & Automation (Design)

Date: 2026-10-26
Status: APPROVED (2026-10-26)

## Intent / Why

The initial Ralph build gave birdROMs a working shape, but a few backend areas are
shallow and the headline feature — cover art — doesn't actually land: scraping runs on
the upload request, only matches ROMs whose titles are *exactly* a libretro No-Intro
name, and ScreenScraper is skipped because no credentials are wired. Uploading is also
clunky (a single file input), and the ROM Django admin is unconfigured.

This round makes cover art **reliable and automatic**, makes **uploading effortless**,
**streamlines native local dev**, and **hardens** the codebase. It builds on the existing
Django + DRF + React stack and the FOSS / Docker-first-for-prod direction.

## Goals

- Drop ROMs anywhere on the page — one or many at once — and they upload.
- Cover art is found and attached **automatically and reliably**, off the request path, for
  normally-named ROMs (not just perfect No-Intro names).
- ROMs carry **real metadata** (description, genre, year, developer/publisher, players,
  rating) when ScreenScraper is configured — not just a title and a cover.
- Local dev is **fully native**: no Docker, no extra daemons to boot the app.
- A genuinely usable ROM admin.
- A cleaner, dependency-audited, security-reviewed codebase.

## Non-goals (this round)

- Deployment/release automation (GitHub Actions image build/publish, compose hardening) —
  explicitly held for a later round.
- Migrating the queue to Celery — only preserve a clean upgrade path.
- SAML SSO; any new auth providers beyond what exists.

## Anti-goals (failure even if it "works")

- Local dev that requires Docker or a broker running just to start the app.
- A queue/infra choice that meaningfully raises idle RAM.
- "Scraping works" that still returns nothing for a reasonably-named ROM.
- Tests that pass on a different database engine than production.

## Constraints

- **Low RAM / lightweight** is a first-order requirement.
- **Native local dev, no Docker.** Connect to the developer's existing local Postgres via
  `.env`; no local Redis required (Huey runs inline in dev).
- **Postgres everywhere** — dev, CI, prod. **No SQLite anywhere**, including tests.
- Preserve the FOSS + Docker-first-for-prod and configurable-auth/storage work already shipped.

## Decisions (the how)

### 1. Global drag-and-drop upload (frontend)
- A page-level drop target: dragging files over the app shows a drop overlay; dropping
  uploads them. Visible only to `super_admin` (matches the existing role gate).
- **Multi-file**: dropping N ROMs performs N uploads (no hard cap), uploaded
  sequentially/throttled so a bulk import doesn't hammer the box; each with per-file
  progress and per-file error reporting, and one failure doesn't abort the rest.
- Reuses the existing `POST /api/roms/` upload endpoint and validation (spec 007).
- Because scraping is now async, a newly uploaded card shows a **placeholder and
  auto-updates** by polling the cover endpoint until art arrives (bounded polling that
  stops once art lands or after a limit) — no manual refresh needed.

### 2. `justfile` for native local dev
- Recipes for the common native tasks: `db-init` (create the `birdroms` DB/role in the
  existing local Postgres if missing), `migrate`, `backend` (runserver), `frontend`
  (`yarn dev`), `test`, `lint`. No `docker` in any default dev recipe.
- Docker remains the production/self-host path only.

### 3. Background jobs via Huey
- **Huey** chosen over Celery for low RAM: one small consumer process, built-in periodic
  tasks (no separate Beat daemon). Leaves a clean Celery upgrade path.
- **Dev:** `immediate` mode (tasks run inline, no worker, no Redis) so the app boots native.
- **Prod:** Redis broker + one Huey consumer process (added to the production compose only).
- Upload **enqueues** a cover-art scrape task instead of scraping inline.
- A `@periodic_task` sweep enqueues scrapes for ROMs still missing art (interval configurable).
- All task definitions live behind a thin wrapper module so a future swap to Celery is a
  localized change.

### 4. Smarter cover-art matching
- **libretro:** fetch and cache the per-system thumbnail **name index**, normalize titles
  (strip region/version/revision tags, punctuation, case), and best-match the ROM title/
  filename against the index before fetching — instead of guessing an exact URL.
- **ScreenScraper:** wire `SS_*` credentials via env (developer supplies their own); query
  with the normalized name; keep it as a fallback/secondary provider.
- Provider configuration and credential presence are observable (logged / surfaced), so a
  silent no-op is diagnosable.

### 4b. ScreenScraper metadata enrichment
- When ScreenScraper credentials are configured, the **same scrape task** also pulls **game
  metadata** and stores it on the ROM: description, genre, release year, developer, publisher,
  player count, and rating (plus region). This adds new nullable ROM fields + a migration.
- libretro provides no metadata, so enrichment is **ScreenScraper-only** and **degrades
  gracefully**: without creds, ROMs keep title/platform/cover and nothing breaks.
- Metadata is exposed in the API serializer, shown on the ROM card/detail in the frontend,
  and displayed in the Django admin. The manual re-scrape action and the periodic sweep
  refresh metadata alongside cover art.
- ScreenScraper uses two credential tiers — per-app **developer** creds (`SS_DEV_ID`/
  `SS_DEV_PASSWORD`, obtained once via ScreenScraper's developer request process) and a
  per-user **member** login (`SS_USER`/`SS_PASSWORD`). Both are operator-supplied env and are
  **never committed** (sharing them in URLs leaks them — per ScreenScraper security advisories).

### 5. ROM Django admin
- A real `ModelAdmin`: `list_display` with a cover thumbnail, title, platform, extension,
  uploader, uploaded-at; `list_filter` by platform; `search_fields` on title; computed
  fields read-only; a bulk admin action **"re-scrape cover art"** that enqueues Huey tasks.

### 6. Postgres everywhere
- Remove the SQLite test configuration from the spec-001 harness; tests run against Postgres.
- CI (spec 014) gains a Postgres **service container**.
- Local tests run against the developer's local Postgres (a `just test` recipe).

### 7. Cleanup sweep (from CLEANUP.md)
- `/code-review` (correctness) and `simplify` (reuse/altitude/efficiency) over the diff.
- Dependency + `.env.example` audit; review the unreviewed baseline edits
  (`App.jsx`, `client.js`, `vite.config.js`, `pyproject.toml`).
- **Dedicated security audit** (`security-review`): auth/OIDC flows, upload handling,
  download access control, S3 credential handling, CSRF / session-vs-token.

## Left to the builder

- libretro name-index source and the match algorithm/threshold (token overlap vs edit
  distance), plus index cache location/TTL.
- Huey retry/backoff policy for scrape tasks and the periodic-sweep interval default.
- Exact `justfile` recipe names and the `db-init` mechanism.
- Admin cover-thumbnail rendering approach.
- Client-side multi-upload concurrency (sequential vs limited-parallel).
- Cover-art poll interval and stop limit for the auto-updating cards.
- Exact ScreenScraper metadata field set, its mapping to ROM columns, and how it's displayed;
  whether the sweep backfills metadata for existing ROMs.
- Test-suite refactor details for Postgres (fixtures, transaction handling).

## Resolved decisions

1. **Security audit:** fix the clear / high-severity findings in this round; report ambiguous
   or large items for a later decision.
2. **Deferred cover art:** ROM cards auto-update by polling the cover endpoint after upload
   (bounded), so art appears without a manual refresh.
3. **Multi-file drop:** no hard cap — accept whatever is dropped, uploaded sequentially/
   throttled.

Reminder: ScreenScraper credentials (`SS_*`) are supplied by the maintainer in their local
`.env` and the deployment env, never committed.
