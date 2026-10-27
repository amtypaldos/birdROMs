# 001 — Backend test harness

## Decisions
- Test mode detected in `settings.py` via `sys.argv[1] == "test"` (no separate settings module),
  so `uv run python manage.py test` works unchanged. Test mode swaps in in-memory SQLite, a
  `tempfile.mkdtemp()` MEDIA_ROOT (removed via `atexit`), and the MD5 hasher for speed.
- Tests use `APITestCase` + `force_authenticate` for the ROM permission matrix; auth endpoints
  are exercised end-to-end through the real register/login views.
- Added an extra case: an authenticated user with no role gets 403 on list.

## Notes for later specs
- The `scrape_cover` action's URL is `/api/roms/{id}/scrape_cover/` (DRF default url_path);
  reverse it as `rom-scrape-cover`. README still says `scrape-cover/` — worth fixing when the
  scraper spec (010) lands.
- Django in the venv is 6.0.x even though the constitution says Django 5.
- The repo has no git remote configured, so pushing is not possible yet.
