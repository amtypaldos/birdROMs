# Upgrading to the ROM library

birdROMs now reads your games straight from a ROM library: a folder (or S3 bucket) laid out the
muOS way, `ROMS/<SYSTEM>/<game file>`, with box art in `ROMS/<SYSTEM>/Imgs/`. A scan runs every 15
minutes and indexes what it finds there. New uploads are written into the library too. birdROMs
never deletes, moves, renames or overwrites files in the library.

If you ran birdROMs before this change, read the points that apply to you.

## Your old uploads are not moved for you

Files uploaded before this change live in the old storage (`roms/...` under `MEDIA_ROOT` or your
bucket). They are not migrated, and after the upgrade their entries stop working. To keep them,
either:

- move each file into the library at `ROMS/<SYSTEM>/` (for example `ROMS/SFC/` for SNES, `ROMS/GBA/`
  for Game Boy Advance), keeping its file name, then rescan; or
- upload it again from the web page.

The first scan marks the old entries as missing (they are hidden, not deleted).

**50 or more old uploads:** the first scan stops with a safety warning, because it would hide more
than a quarter of your games at once (it can't tell this from a NAS that went offline). Check the
library is mounted, then press **Accept removals** on the Library page once (or run
`python manage.py scan_library --accept-removals`).

## S3 deployments

The library uses the same bucket and `S3_*` settings as file storage, plus `LIBRARY_S3_PREFIX` for
the folder inside the bucket that holds `ROMS/`. The library is rooted at that prefix; the default,
empty, means the bucket root.

With an empty prefix (and no `S3_LOCATION`), the old media folders `roms/` and `covers/` sit inside
the library. Your old uploads then stay downloadable (they are not hidden), and when your system
folders sit directly at the bucket root (no `ROMS/` folder) those two folders show up as unknown
folders in the scan report. For a clean separation, set `LIBRARY_S3_PREFIX` (for example
`library/`) and keep `ROMS/` under it (`library/ROMS/SFC/...`).

`LIBRARY_BACKEND` now defaults to the value of `STORAGE_BACKEND`, so an install with
`STORAGE_BACKEND=s3` keeps an S3 library without changes. Set `LIBRARY_BACKEND` explicitly to
choose otherwise (for example `LIBRARY_BACKEND=filesystem` with `LIBRARY_ROOT`).

## Docker

- The containers run as uid 1000 (set `PUID`/`PGID` to match the library; TrueNAS `apps` is 568) and mount the library at `/library`. A `birdroms_library` volume
  created before this change is still owned by root, so uploads and cover saving fail. Fix it once
  with
  `docker compose -f docker-compose.prod.yml run --rm --no-deps --user root backend chown -R 1000:1000 /library`,
  or remove the volume and let Compose recreate it (only if it holds nothing you need).
- The image default is uid/gid 1000. Older images used 999, then 568 (TrueNAS's `apps` account). Pick another at
  runtime with `PUID`/`PGID` in `backend/.env` (or compose `user:`); `PUID=999 PGID=999` keeps
  the old owner and needs no chown. Volumes written by an older
  image are owned by that older uid: give them to the user you run as once with
  `docker compose -f docker-compose.prod.yml run --rm --no-deps --user root backend chown -R 1000:1000 /data/media /library`.
- For a library on an NFS share, that uid needs write access to the export. If you don't want
  birdROMs to write there at all, set `LIBRARY_READ_ONLY=true` (uploads and cover saving are then
  turned off).

## Database connection pooling

Scans use a Postgres advisory lock so only one runs at a time. That lock needs a database
connection that stays the same for the whole scan: point birdROMs straight at Postgres, or use
PgBouncer in session pooling mode, not transaction pooling.

## Running without Docker

The default library folder is `/library`, which usually doesn't exist on a laptop or a bare
server. Set `LIBRARY_ROOT` in `backend/.env` to your library folder (the one that contains `ROMS/`),
for example `LIBRARY_ROOT=/Users/me/roms-library`.
