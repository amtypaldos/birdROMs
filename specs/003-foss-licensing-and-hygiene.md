# 003 — FOSS licensing & project hygiene

## Status: DRAFT
Priority: 3

## Problem / Context
birdROMs should be free and open-source so others can deploy it, but the repo has **no
LICENSE, no contribution guide, and no self-hosting framing**. There is also a committed
`backend/.env` risk — secrets must never live in the repo. This spec establishes the
open-source baseline.

> Default license: **MIT** (confirm with the maintainer; swap if a copyleft license like
> AGPL-3.0 is preferred).

## Acceptance Criteria
- A `LICENSE` file at the repo root (MIT by default), with the correct copyright line.
- `README.md` gains a **License** section and a short "Self-hosting / Open source" intro
  making clear anyone can run their own instance.
- `CONTRIBUTING.md` documents local dev setup (backend via `uv`, frontend via `yarn`/corepack),
  how to run the test suites, and PR expectations (tests + lint must pass).
- A complete root-level `.gitignore` covering `.venv/`, `node_modules/`, `dist/`,
  `__pycache__/`, `*.env`/`.env`, `media/`, and build artifacts.
- `backend/.env` is **not** tracked by git (`git check-ignore backend/.env` succeeds); if it is
  currently tracked, it is removed from the index (file kept on disk). `backend/.env.example`
  exists and documents every variable without real secrets.

## Completion Signal
Implementation:
- [ ] LICENSE added; README License + self-hosting section added.
- [ ] CONTRIBUTING.md added.
- [ ] .gitignore complete; `.env` untracked; `.env.example` present.

Testing:
- [ ] `git check-ignore backend/.env` returns the path (ignored).
- [ ] `git ls-files | grep -E '(^|/)\.env$'` returns nothing.
- [ ] Backend + frontend test suites still pass.

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 0 -->
