# birdROMs Constitution

> birdROMs is a Django + React web app for private retro ROM sharing and management.
> It lets a small, trusted group upload and browse a shared library of retro game ROMs,
> with role-based access (`super_admin` can upload/manage, `readonly` can browse and
> download), automatic platform classification from file extension (`.nes`, `.sfc`,
> `.gba`, …), cover-art scraping, and metadata storage. The goal is a clean,
> self-hostable library that is pleasant to browse and safe to share privately. birdROMs is
> free and open-source and is designed for anyone to self-host: every deployment-specific
> value is configured via environment variables and documented, with no secrets in the repo.

> Ralph Wiggum installed from https://github.com/fstandhartinger/ralph-wiggum @ 3f15f0fb83b8c2e0ac8d11abdae0e83ab8204981

---

## Context Detection

**Ralph Loop Mode** (started by `scripts/ralph-loop.sh`):
- Pick the highest-priority incomplete spec from `specs/` (lower number = higher priority).
- Implement, test, commit, push.
- Output `<promise>DONE</promise>` only when the current spec is 100% complete.
- Output `<promise>ALL_DONE</promise>` when no incomplete work remains.

**Interactive Mode** (normal conversation):
- Be helpful, guide decisions, create and refine specs.

---

## Core Principles

- **Private-by-default & safe sharing** — respect the role model; never widen access or
  expose ROMs/media beyond what a role permits. Treat uploaded files as untrusted.
- **FOSS & self-hostable** — birdROMs is open-source and meant for others to deploy. Favor
  straightforward Django/DRF + React patterns over cleverness; every environment-specific
  value (DB, auth, storage, scraper creds) is env-configurable and documented, and no secrets
  ever live in the repo.
- **Quality you can trust** — every change ships with tests and leaves `main` runnable;
  no spec is "done" until its acceptance criteria are verified.

---

## Technical Stack

- **Backend:** Django 5 + Django REST Framework, SimpleJWT auth, PostgreSQL (psycopg2),
  python-dotenv. Managed with `uv` (`backend/`). Local media storage via `MEDIA_ROOT`.
- **Frontend:** React + Vite, Yarn (corepack) (`frontend/`). Talks to the API at
  `http://localhost:8000/api`.
- **Roles:** implemented as Django groups — `super_admin`, `readonly`.
- **Auth:** pluggable login methods, each enabled via env — local username/password and
  OIDC/SSO (Pocket ID is the reference provider; any standard OIDC provider such as Authentik,
  Keycloak, Authelia or Google works through the same path). Local login also honors
  `ALLOW_LOCAL_LOGIN` (on under DEBUG).
- **Storage:** pluggable via `django-storages` — local/NFS filesystem (default) or
  S3-compatible (MinIO/R2/B2/AWS), selected by env.
- **Cover art:** auto-downloaded on upload from libretro-thumbnails and ScreenScraper.
- **Deployment:** Docker is the first-class, supported path — a dev compose and a production
  compose, fully env-driven, are the blessed way to run birdROMs.
- **Orchestration:** `docker-compose.yml` at repo root.

### Commands
- Backend: `cd backend && uv run python manage.py <cmd>` (`migrate`, `test`, `runserver`).
- Frontend: `cd frontend && yarn <cmd>` (`dev`, `build`, `lint`, `test` if present).
- Run backend tests before marking any backend spec complete; run `yarn build` (and lint)
  before marking any frontend spec complete.

---

## Autonomy

YOLO Mode: ENABLED
Git Autonomy: ENABLED (commit **and** push after each completed spec)

Work autonomously: run commands, edit files, run tests, commit, and push without asking.
Keep commits focused (one spec per commit where practical) with clear messages. Never
force-push; never rewrite published history; never touch secrets in `backend/.env`.

---

## Specs

Specs live in `specs/` as markdown files. Pick the highest-priority incomplete spec
(lower number = higher priority). A spec is incomplete if it lacks `## Status: COMPLETE`.
Each spec should have clear acceptance criteria and a Completion Signal section listing
implementation + testing requirements.

Spec template: https://raw.githubusercontent.com/github/spec-kit/refs/heads/main/templates/spec-template.md

When all specs are complete, re-verify a random one before signaling done.

---

## NR_OF_TRIES

Track attempts per spec via `<!-- NR_OF_TRIES: N -->` at the bottom of the spec file.
Increment each attempt. At 10+, the spec is too hard — split it into smaller specs.

---

## History

Append a 1-line summary to `history.md` after each spec completion. For details, create
`history/YYYY-MM-DD--spec-name.md` with lessons learned, decisions made, and issues
encountered. Check history before starting work on any spec.

---

## Completion Logs

After each spec, create `completion_log/YYYY-MM-DD--HH-MM-SS--spec-name.md` with a brief
summary of what was implemented, how it was verified, and anything left as follow-up.

---

## Development Skills (Superpowers)

This project uses the Superpowers skill plugins (installed at user/project scope). When a skill
applies to the current task, **invoke it** — don't reinvent its workflow.

Coding (`superpowers:*`):
- **test-driven-development** — the default for every spec: write the failing test(s) first,
  then the implementation. These specs are acceptance-criteria driven, so TDD fits directly.
- **systematic-debugging** — use whenever a test fails or behavior is unexpected, before
  guessing at a fix.
- **verification-before-completion** — run the spec's verification commands and confirm the
  real output **before** emitting `<promise>DONE</promise>`. Evidence before assertions.
- **requesting-code-review** — self-review a substantial spec against its acceptance criteria
  before marking it complete.
- **brainstorming** / **writing-plans** — in Interactive Mode when shaping or splitting specs
  (not required inside the build loop).

Design (`frontend-design:*`):
- **frontend-design** — use for any frontend/UI spec (e.g. 011 role-aware UI, 012 retro
  redesign): intentional typography, color, and layout over templated defaults.

---

## Completion Signal

All acceptance criteria verified, tests pass, changes committed and pushed → output
`<promise>DONE</promise>`. Never output this until truly complete. Gate this on the
**verification-before-completion** skill: confirm real command output first.
