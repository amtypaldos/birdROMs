# 010 — Auto-download cover art / thumbnails

## Status: DRAFT
Priority: 10

## Problem / Context
`scrape_cover_art` is a placeholder that returns nothing, and cover art is only fetched on a
manual button press. Cover art should **auto-download on upload**, using real providers:
**libretro-thumbnails** (free, no key) and **ScreenScraper** (operator-provided account). The
image should be stored in the configured storage backend (spec 005) so it works fully offline.

## Acceptance Criteria
- Real provider implementations:
  - **libretro-thumbnails**: match by mapping the ROM's platform to the libretro system name and
    the title to the thumbnail path; fetch boxart (fallback to title/snap). No credentials.
  - **ScreenScraper**: use env credentials (`SS_DEV_ID`, `SS_DEV_PASSWORD`, `SS_USER`,
    `SS_PASSWORD` or equivalent); query by name/platform. Optional — skipped if unconfigured.
  - Provider order is configurable; try in order until one returns an image. Each call has a
    timeout.
- The fetched image is saved to the configured storage and referenced by the ROM (store the
  image as a media asset, not just a remote hotlink); `cover_art_source` records the provider.
- Auto-trigger on ROM create **after** a successful upload. Scrape failures must **not** fail the
  upload (log + continue).
- The manual `scrape_cover` action remains (force re-scrape), and a management command backfills
  missing art for existing ROMs.
- All provider config documented in `.env.example`; ScreenScraper creds optional.
- Covered by backend tests with mocked HTTP (no live provider calls).

## Completion Signal
Implementation:
- [ ] libretro + ScreenScraper providers with configurable order + timeouts.
- [ ] Art stored in configured storage; source recorded.
- [ ] Auto-scrape on upload (non-fatal on failure) + backfill command.

Testing:
- [ ] Backend tests (mocked HTTP): a match sets cover art; no-match leaves it empty; a provider
      error does not break the upload.
- [ ] `uv run python manage.py test` passes.

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 0 -->
