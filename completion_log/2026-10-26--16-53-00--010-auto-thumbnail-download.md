# 010 auto-thumbnail-download — completion

Implemented: libretro-thumbnails and ScreenScraper providers with configurable order and per-request
timeout; images saved to the configured storage and recorded in `cover_art_source`; non-fatal auto-scrape
on upload; manual `scrape_cover` re-scrape; `backfill_cover_art` management command (`--force`);
permission-checked `/api/roms/{id}/cover/`; frontend authenticated cover loading; `.env.example` + README docs.

Verified: `uv run python manage.py test` → 105 tests OK (mocked HTTP: match stores art, no match leaves it empty,
provider error / unexpected error keep the upload 201, fallthrough between providers, backfill, permissions);
`makemigrations --check` clean; `yarn test` 22 passed, `yarn lint` exit 0, `yarn build` OK.

Follow-up: async scraping if upload latency becomes a problem; storage cleanup on ROM delete.
