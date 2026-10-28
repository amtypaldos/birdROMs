# Serving the handheld app

Signed-in users get a **Handheld** page (`#/handheld`) with install steps and a download button for the
muOS app (`birdROMs.muxapp`). The server just stores one file and serves it to signed-in users
(`GET /api/handheld/` for details, `GET /api/handheld/download/` for the file).

## Publish a new version

1. Build the package in the handheld repo: `just package` (writes `dist/birdROMs.muxapp`).
2. Put it on the server:

   ```
   python manage.py publish_handheld path/to/birdROMs.muxapp
   ```

   The command checks that the file is a real birdROMs package, then replaces the published one
   atomically. With Docker, copy the file into the container first (for example
   `docker compose cp dist/birdROMs.muxapp backend:/tmp/` and then
   `docker compose exec backend python manage.py publish_handheld /tmp/birdROMs.muxapp`).
   Adjust the service name to your compose file.
3. That is all. The page shows the new size and date; friends re-download and reinstall (the
   friend-facing steps are in the handheld repo's `docs/install.md`). Their pairing is kept.

Where the file lives: `HANDHELD_APP_PATH` (default `MEDIA_ROOT/handheld/birdROMs.muxapp`, so it sits
on the same volume as uploads). Until something is published the page says so.
