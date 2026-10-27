# 003 — FOSS licensing & project hygiene

- **License:** MIT, the spec's default. The copyright line is "Alex Typaldos and birdROMs
  contributors". The maintainer can still swap it for AGPL-3.0 if they want copyleft.
- `backend/.env` was already untracked and ignored by the root `*.env` rule, so nothing had to be
  removed from the index.
- `.gitignore` additions: `media/` (broadened from `backend/media/`), `build/`, `*.egg`, `.coverage`,
  `htmlcov/`, `coverage/`.
- `.env.example` keeps `POSTGRES_PASSWORD=birdroms` because the dev `docker-compose.yml` uses that
  password, and a placeholder there would break the quickstart. A comment says to change it in
  production.
- Removed the stale "Important Note About Git Init" section from the README.
- README now says birdROMs ships no ROMs. CONTRIBUTING bans committing ROMs as test fixtures.
