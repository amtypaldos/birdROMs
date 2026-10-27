# birdROMs Backend Polish & Automation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make cover art reliable and automatic (async + smarter matching + ScreenScraper metadata), make uploading effortless (global multi-file drag-drop), give ROMs a real admin, run Postgres everywhere, add a native-dev `justfile`, and finish with a security/cleanup pass.

**Architecture:** Django + DRF backend, React + Vite frontend. Background work runs on **Huey** (immediate/in-process in dev, one Redis-backed consumer in prod), behind a thin `tasks` wrapper so a future Celery swap is localized. Cover-art/metadata scraping moves off the upload request into a Huey task; a periodic task backfills. Scraping providers (libretro + ScreenScraper) are config-driven and degrade gracefully when unconfigured.

**Tech Stack:** Python 3.11+, Django 5, DRF, `huey`, `requests`, PostgreSQL (psycopg2), `uv`; React 18, Vite, Vitest + Testing Library, Yarn.

**Spec:** `docs/superpowers/specs/2026-10-26-backend-polish-design.md` (read it alongside this plan).

## Global Constraints

- Python **3.11+**, Django **5.x**, DRF; frontend React **18**, Vite **5**.
- **Postgres everywhere** — dev, CI, prod. **No SQLite** in any settings/test path.
- Background jobs via **Huey**; dev uses `immediate=True` (no Redis/worker to boot); prod uses a Redis broker + one consumer. All task definitions go through `backend/birdroms/tasks.py` (thin wrapper) — never import `huey` directly in app code.
- **No secrets in the repo.** All provider/storage/queue config via env; document every new var in `backend/.env.example`.
- Cover-art/metadata scraping must **never fail an upload** and must **never crash the worker**.
- Match existing code style; keep files focused. **TDD**: test first, then minimal code. **Commit after every task.**
- Backend tests: `cd backend && uv run python manage.py test`. Frontend: `cd frontend && yarn lint && yarn test && yarn build`.

## Review Focus

Input classes the spec implies but happy-path tests won't catch — each pinned to a task below:

1. **Provider/network failure mid-scrape** (timeout, 500, malformed JSON) → task logs and exits cleanly; ROM keeps whatever it had; upload already succeeded. *(Task 3)*
2. **Concurrent scrape of the same ROM** (upload enqueue racing the periodic sweep) → no double download, no half-written cover; last write wins without corruption. *(Task 5)*
3. **libretro fuzzy-match false positive** (similar-but-wrong title) → below threshold yields **no** match rather than wrong art. *(Task 4)*
4. **Multi-file drop with a bad file** (disallowed ext / oversized / zero-byte among good ones) → that file reports its error, the rest still upload. *(Task 7)*
5. **Deferred-cover poll that never resolves** (ROM genuinely has no art) → polling stops after a bounded number of attempts, never loops forever. *(Task 8)*

---

## File Structure

- `backend/birdroms/tasks.py` — **new**. Thin Huey wrapper: exposes the configured `huey` instance + `@task`/`@periodic_task` re-exports and the app's task functions. Single seam for a future Celery swap.
- `backend/birdroms/settings.py` — **modify**. Huey config (immediate in dev, Redis in prod); remove any SQLite test-DB branch so tests use Postgres.
- `backend/apps/roms/cover_art.py` — **modify**. Add libretro name-index fuzzy matching; add ScreenScraper metadata parsing; keep `fetch_cover_for_rom` but have it also populate metadata.
- `backend/apps/roms/models.py` — **modify**. New metadata fields.
- `backend/apps/roms/migrations/0003_rom_metadata.py` — **new**.
- `backend/apps/roms/serializers.py` — **modify**. Expose metadata fields (read-only).
- `backend/apps/roms/views.py` — **modify**. `perform_create` enqueues the scrape task; `scrape_cover` action enqueues too (or runs sync — see Task 3).
- `backend/apps/roms/admin.py` — **modify**. Real `ROM` ModelAdmin.
- `backend/apps/roms/tests.py` — **modify**. New tests per task.
- `frontend/src/App.jsx` — **modify**. Global drag-drop overlay (super_admin, multi-file); auto-updating cover cards.
- `frontend/src/api/client.js` — **modify**. Cover-poll helper if needed.
- `frontend/src/App.test.jsx` — **modify**. Drag-drop + polling tests.
- `justfile` — **new** (repo root). Native dev recipes.
- `.github/workflows/ci.yml` — **modify**. Postgres service for the backend job.
- `backend/.env.example` — **modify**. New env vars.
- `docs/superpowers/reports/2026-10-26-security-audit.md` — **new** (Task 11).

---

### Task 1: Postgres everywhere (drop SQLite from tests)

**Files:**
- Modify: `backend/birdroms/settings.py`
- Modify: `backend/apps/roms/tests.py` / `backend/apps/accounts/tests.py` (only if they assumed SQLite)

**Interfaces:**
- Produces: a test run that uses the Postgres config from env (a dedicated `test_<db>` database Django creates). No SQLite anywhere.

- [ ] **Step 1: Find and read the SQLite test branch** in `settings.py` (added by spec 001 — e.g. a `"test" in sys.argv` or separate `DATABASES` for tests). Confirm how tests currently pick SQLite.
- [ ] **Step 2: Remove it** so `DATABASES["default"]` (Postgres, env-driven) is used for tests too. Keep all connection values from env.
- [ ] **Step 3: Run the full suite against local Postgres** — `cd backend && uv run python manage.py test`. Expected: PASS (Django creates/drops `test_<POSTGRES_DB>`). Fix any test that depended on SQLite-only behavior.
- [ ] **Step 4: Commit** — `git commit -m "test: run the suite on Postgres, drop the SQLite shortcut"`.

---

### Task 2: Huey wrapper + settings

**Files:**
- Create: `backend/birdroms/tasks.py`
- Modify: `backend/birdroms/settings.py`, `backend/pyproject.toml` (+`requirements.txt`), `backend/.env.example`
- Test: `backend/birdroms/tests.py`

**Interfaces:**
- Produces: `from birdroms.tasks import task, periodic_task, huey` — the configured instance and decorators. `HUEY` setting: `immediate=True` when `DEBUG` or `HUEY_IMMEDIATE=true`; else `RedisHuey` from `REDIS_URL`.

- [ ] **Step 1: Write the failing test** — `test_huey_immediate_in_debug`: with `DEBUG`/`HUEY_IMMEDIATE` on, `birdroms.tasks.huey.immediate is True`; and `test_redis_backend_selected_when_not_immediate` asserts the instance is a Redis-backed Huey when `HUEY_IMMEDIATE=false` + `REDIS_URL` set (construct via the settings helper; no live Redis needed).
- [ ] **Step 2: Run it** — `uv run python manage.py test birdroms.tests -v`. Expected: FAIL (module/attr missing).
- [ ] **Step 3: Add `huey` dep**, configure `HUEY` in settings, and implement `backend/birdroms/tasks.py` exposing `huey`, `task`, `periodic_task`. Document `HUEY_IMMEDIATE` and `REDIS_URL` in `.env.example`.
- [ ] **Step 4: Run it** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: add Huey task wrapper (immediate in dev, Redis in prod)"`.

---

### Task 3: Move cover-art scrape into a Huey task (+ graceful failure)

**Files:**
- Modify: `backend/birdroms/tasks.py` (add `scrape_rom_cover`), `backend/apps/roms/views.py`
- Test: `backend/apps/roms/tests.py`

**Interfaces:**
- Consumes: `fetch_cover_for_rom(rom)` / `safe_fetch_cover_for_rom(rom)` from `cover_art.py` (Task 5 extends these to also set metadata).
- Produces: `scrape_rom_cover(rom_id: int) -> bool` (Huey task) — loads the ROM, calls `safe_fetch_cover_for_rom`, returns whether art/metadata changed; missing ROM is a no-op.

- [ ] **Step 1: Write failing tests** — `test_upload_enqueues_scrape` (POST a ROM as super_admin → `scrape_rom_cover` was enqueued/called with the new id; patch the task); `test_scrape_task_missing_rom_is_noop` (unknown id returns False, no raise); `test_scrape_task_swallows_provider_error` (patch `fetch_cover_for_rom` to raise → task returns False, worker survives). *(Review Focus #1)*
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `scrape_rom_cover` in `tasks.py` wrapping `safe_fetch_cover_for_rom`; change `ROMViewSet.perform_create` to `scrape_rom_cover(rom.id)` enqueue instead of the inline call. In dev (immediate) it still runs inline, so no UX change locally.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: scrape cover art via Huey task on upload"`.

---

### Task 4: Smarter libretro matching (name index + fuzzy)

**Files:**
- Modify: `backend/apps/roms/cover_art.py`
- Test: `backend/apps/roms/tests.py`

**Interfaces:**
- Produces: `normalize_title(name: str) -> str` (lowercase, strip region/version/revision tags and punctuation); `best_libretro_name(title: str, platform: str, index: list[str]) -> str | None` (returns the index entry whose normalized form best matches, or None below threshold); `libretro_name_index(system: str) -> list[str]` (fetch + cache the system's Named_Boxarts listing).
- Keeps `find_libretro(...)` returning candidate URLs, now built from the matched index name rather than an exact guess.

- [ ] **Step 1: Write failing tests** — `test_normalize_title_strips_tags` (`"Super Mario Bros. (USA) (Rev 1)"` → `"super mario bros"`); `test_best_match_picks_closest` (index has the No-Intro name, a loosely-typed title matches it); `test_best_match_rejects_false_positive` (a clearly different title → None). *(Review Focus #3)* Mock the index fetch.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** normalization, the cached index fetch (HTTP mocked in tests; cache in-process/Django cache with a TTL), and threshold matching (token-set ratio or Levenshtein ratio — implementer's choice; pin the threshold as a module constant). Wire `find_libretro` to use it.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: fuzzy libretro cover matching via name index"`.

---

### Task 5: ScreenScraper metadata enrichment

**Files:**
- Modify: `backend/apps/roms/models.py`, `backend/apps/roms/cover_art.py`, `backend/apps/roms/serializers.py`
- Create: `backend/apps/roms/migrations/0003_rom_metadata.py`
- Test: `backend/apps/roms/tests.py`

**Interfaces:**
- Produces: new nullable ROM fields `description`, `genre`, `release_year` (int), `developer`, `publisher`, `players`, `rating`, `region` (all `blank=True`/nullable). `parse_screenscraper_metadata(jeu: dict) -> dict` mapping an SS `jeu` payload to those fields (region-preferred text, best-effort). `fetch_cover_for_rom` also sets metadata when the SS provider returns a game.

- [ ] **Step 1: Write failing tests** — `test_parse_ss_metadata` (sample `jeu` dict → expected field dict, incl. year parsed from date, region-preferred description); `test_fetch_sets_metadata` (SS mocked to return a game → ROM gets description/genre/etc. + cover); `test_concurrent_scrape_no_corruption` (two sequential `fetch_cover_for_rom` calls on the same ROM leave exactly one valid cover + consistent metadata). *(Review Focus #2)*
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** the model fields + migration `0003_rom_metadata`, `parse_screenscraper_metadata`, extend the SS path in `cover_art.py` to capture the `jeu` payload and persist metadata alongside the cover (`update_fields` includes the new columns), and expose the fields read-only in `ROMSerializer`. Document `SS_*` in `.env.example`.
- [ ] **Step 4: Run** — Expected: PASS; run `makemigrations --check` to confirm no missing migration.
- [ ] **Step 5: Commit** — `git commit -m "feat: enrich ROMs with ScreenScraper metadata"`.

---

### Task 6: Periodic backfill sweep

**Files:**
- Modify: `backend/birdroms/tasks.py`, `backend/.env.example`
- Test: `backend/apps/roms/tests.py`

**Interfaces:**
- Produces: `sweep_missing_cover_art()` (`@periodic_task`, hourly by default via `crontab`) that enqueues `scrape_rom_cover` for each ROM with no `cover_art`. Interval overridable by `COVER_ART_SWEEP_CRONTAB` or similar.

- [ ] **Step 1: Write failing test** — `test_sweep_enqueues_only_missing`: given ROMs some with/without cover, the sweep enqueues `scrape_rom_cover` only for the ones missing art (patch the task; assert the id set).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `sweep_missing_cover_art` as a `@periodic_task`; factor the "ROMs missing art" query so the test can call the body directly.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: periodic sweep to backfill missing cover art"`.

---

### Task 7: ROM Django admin

**Files:**
- Modify: `backend/apps/roms/admin.py`
- Test: `backend/apps/roms/tests.py`

**Interfaces:**
- Produces: a `ROMAdmin(ModelAdmin)` with `list_display` (cover thumbnail, title, platform, extension, uploaded_by, uploaded_at), `list_filter=("platform",)`, `search_fields=("title",)`, read-only computed fields (extension, cover_art_source, uploaded_at, a rendered thumbnail), and a bulk action `rescrape_cover_art` that enqueues `scrape_rom_cover` for selected ROMs.

- [ ] **Step 1: Write failing tests** — `test_admin_changelist_loads` (admin client GET `/admin/roms/rom/` → 200, shows title/platform columns); `test_admin_rescrape_action` (running the action on selected ROMs enqueues `scrape_rom_cover` for each — patch the task).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `ROMAdmin` (replace the bare `admin.site.register(ROM)`), with a `thumbnail` method returning an `<img>` via `format_html` from the cover endpoint/field, and the `rescrape_cover_art` admin action.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: build out the ROM Django admin"`.

---

### Task 8: Frontend — global multi-file drag-drop upload

**Files:**
- Modify: `frontend/src/App.jsx`, `frontend/src/api/client.js`
- Test: `frontend/src/App.test.jsx`

**Interfaces:**
- Consumes: `api.createRom(formData)` (existing).
- Produces: a page-level dropzone (dragover → overlay; drop → upload each file) rendered only for `super_admin`; per-file progress + per-file error; sequential/throttled uploads.

- [ ] **Step 1: Write failing tests** — `test_dropzone_super_admin_only` (overlay/handlers absent for readonly, present for super_admin); `test_multi_drop_uploads_each` (drop 3 files → `createRom` called 3×); `test_one_bad_file_does_not_abort_rest` (one `createRom` rejects → others still complete, error shown for the bad one). *(Review Focus #4)*
- [ ] **Step 2: Run** — `yarn test` — Expected: FAIL.
- [ ] **Step 3: Implement** the global drop handlers + overlay, gated on role from `/api/auth/me/`; upload files sequentially with per-file status; surface per-file errors.
- [ ] **Step 4: Run** — `yarn test && yarn lint && yarn build` — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: global multi-file drag-and-drop upload"`.

---

### Task 9: Frontend — auto-updating cover cards

**Files:**
- Modify: `frontend/src/App.jsx`, `frontend/src/api/client.js`
- Test: `frontend/src/App.test.jsx`

**Interfaces:**
- Produces: after an upload, the new card shows a placeholder and polls the cover endpoint (`api.coverExists(id)` or a HEAD/GET on `/api/roms/{id}/cover/`) on an interval, swapping in the art when it appears; polling **stops after a bounded number of attempts** or once art loads.

- [ ] **Step 1: Write failing tests** — `test_card_polls_then_shows_cover` (fake timers: cover 404 then 200 → `<img>` appears, polling stops); `test_poll_gives_up_after_limit` (always 404 → polling stops after N attempts, placeholder remains, no infinite calls). *(Review Focus #5)*
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** the bounded poll (interval + max attempts as constants) and placeholder→art swap.
- [ ] **Step 4: Run** — `yarn test && yarn lint && yarn build` — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: auto-updating cover art cards"`.

---

### Task 10: `justfile` + CI Postgres

**Files:**
- Create: `justfile` (repo root)
- Modify: `.github/workflows/ci.yml`, `README.md` (dev section)

**Interfaces:**
- Produces: `just` recipes — `db-init` (create the `birdroms` DB/role in local Postgres if absent, via `psql`/`createdb`, idempotent), `migrate`, `backend` (`uv run python manage.py runserver`), `frontend` (`yarn dev`), `test` (backend + frontend), `lint`. No `docker` in any recipe.

- [ ] **Step 1: Write the `justfile`** with the recipes above (native commands only).
- [ ] **Step 2: Verify** — `just --summary` lists them; `just lint` and `just test` run green against local Postgres.
- [ ] **Step 3: Update CI** — add a `postgres` service container to the backend job in `ci.yml`, point env at it, run `uv run python manage.py test`. Validate YAML (`python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"`). Note the justfile in the README dev section.
- [ ] **Step 4: Commit** — `git commit -m "chore: add native-dev justfile and Postgres CI"`.

---

### Task 11: Security & cleanup pass

**Files:**
- Create: `docs/superpowers/reports/2026-10-26-security-audit.md`
- Modify: whatever the clear findings touch (auth, uploads, downloads, storage, CSRF).

**Interfaces:**
- Produces: a written audit (findings + severity + status) and fixes for the clear/high-severity ones; ambiguous/large items listed as follow-ups.

- [ ] **Step 1:** Run `security-review` over the branch; also `/code-review` and `simplify`. Record all findings in the audit report.
- [ ] **Step 2:** Audit dependencies and `backend/.env.example` for completeness/accuracy; review the previously-unreviewed baseline edits (`App.jsx`, `client.js`, `vite.config.js`, `pyproject.toml`) and note anything off.
- [ ] **Step 3:** Fix the **clear/high-severity** findings (add a regression test per fix where it's code); leave ambiguous/large ones as documented follow-ups.
- [ ] **Step 4: Verify** — full backend + frontend suites green (`uv run python manage.py test`; `yarn test && yarn lint && yarn build`).
- [ ] **Step 5: Commit** — `git commit -m "fix: address clear security-audit findings; add audit report"`.

---

## Self-Review

**Spec coverage:** drag-drop (T8) ✓ · justfile (T10) ✓ · Huey async scrape (T2,T3) ✓ · periodic sweep (T6) ✓ · smarter libretro matching (T4) ✓ · ScreenScraper metadata (T5) ✓ · ROM admin (T7) ✓ · Postgres everywhere (T1,T10) ✓ · cleanup+security (T11) ✓ · auto-updating covers (T9) ✓. Held per spec: deployment scripts — not planned. ✓

**Review Focus:** #1→T3, #2→T5, #3→T4, #4→T8, #5→T9 — each has a named test. ✓

**Type consistency:** `scrape_rom_cover(rom_id)` used identically in T3, T6, T7; `fetch_cover_for_rom`/`safe_fetch_cover_for_rom` names match existing code; `normalize_title`/`best_libretro_name` defined T4 and not redefined. ✓

**Proportion:** interfaces + test names/assertions only, no full bodies — plan is shorter than the code it describes. ✓

**Ordering note:** T1→T2 are foundational; T3 depends on T2; T5 extends the scrape path T3 uses; T6/T7 depend on `scrape_rom_cover` (T3); T8/T9 are frontend and depend only on existing endpoints + `/me`; T10/T11 last. A fresh implementer can take tasks in number order.
