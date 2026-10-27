# 010 — Auto-download cover art

## Decisions
- **Stored file, not hotlink.** The `ROM.cover_art_url` URLField was replaced with a `cover_art` FileField
  (`covers/rom-<id>.<ext>`, migration 0002). The serializer still exposes `cover_art_url`, but it is now
  computed: the absolute URL of `GET /api/roms/{id}/cover/`, or `null` when there is no art.
- **Covers are private like ROMs.** Following the 006 note, there is no media route. The cover endpoint
  streams from storage through the same role permission. Because `<img>` can't send the token, the
  frontend `CoverImage` fetches a blob via `api.coverObjectUrl` and revokes the object URL on unmount.
- **Provider module** `apps/roms/cover_art.py`: finders return candidate image URLs; `download_image`
  accepts only `image/*` content types (png/jpeg/gif/webp) up to 10 MB, streamed. libretro tries title then
  file stem (with Django's 7-char dedup suffix stripped), boxart → titles → snaps. ScreenScraper uses
  `jeuInfos.php` with `romnom`, `systemeid` and ranks `box-2D` > `sstitle` > `ss`, preferring us/wor/eu regions.
- **Config** parsed in `parse_cover_art_settings` (imported by settings.py). Unknown providers and bad timeouts
  raise ImproperlyConfigured. Tests set `COVER_ART_PROVIDERS=""` globally so no test ever hits the network,
  and scraping tests opt in with `override_settings` + a mocked `requests.get`.
- Auto-scrape runs synchronously in `perform_create` after save, wrapped in `safe_fetch_cover_for_rom`
  (logs and swallows every exception).
- Manual re-scrape deletes the previous stored image if its name changed.

## Follow-ups
- Worst-case upload latency is about (candidate URLs × timeout) when providers hang. A task queue
  (or `on_commit` + thread) would decouple it if that becomes a problem.
- Deleting a ROM does not delete its ROM file or cover from storage (this was already true before this spec).
- Still no git remote, so push is skipped.
