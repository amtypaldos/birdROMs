# Serving the handheld app

Signed-in users get a **Handheld** page (`#/handheld`) with install steps and a download button for the
muOS app (`birdROMs.muxapp`). The server just stores one file and serves it to signed-in users
(`GET /api/handheld/` for details, `GET /api/handheld/download/` for the file).

The download is personalised: the server adds a small `server.json` (its own address, taken from the
request, so it honours your proxy settings) to the package. The handheld has no keyboard, so that is how
the app learns which server to pair with. Make sure friends open the site at the address you want baked
in (your public https address, not `localhost`).

## Publish a new version

The file [`handheld-version`](../handheld-version) names the handheld release the image bundles
(for example `v2026.10.29.2`). A push to `main` and a server release tag both download that
release. On startup the container copies the file into the media volume when it differs from
what is already published. Tag the handheld repo when the app changes, set `handheld-version`
to that tag, then tag this repo when the image should ship. A site-only release leaves the pin
as it is. See [CONTRIBUTING.md](../CONTRIBUTING.md#releases).

Until the handheld repo is public, add a secret `HANDHELD_RELEASE_TOKEN` on this repo that can read
it. After it is public, the workflow token is enough.

To publish a package by hand instead:

1. Get the package: download `birdROMs.muxapp` from the [birdroms-handheld releases](https://github.com/amtypaldos/birdroms-handheld/releases), or build it in that repo with `just package` (writes `dist/birdROMs.muxapp`).
2. Put it on the server:

   ```
   python manage.py publish_handheld path/to/birdROMs.muxapp
   ```

   The command checks that the file is a real birdROMs package, then replaces the published one
   atomically. With Docker, copy the file into the container first (for example
   `docker compose cp dist/birdROMs.muxapp backend:/tmp/` and then
   `docker compose exec -u "${PUID:-1000}:${PGID:-1000}" backend python manage.py publish_handheld /tmp/birdROMs.muxapp`;
   `exec` runs as root unless you pass `-u`, and the file must belong to the app user).
   Adjust the service name to your compose file.
3. That is all. The page shows the new size and date. Paired handhelds download it the next time
   they open the app. New friends install from the Handheld page (see the handheld repo's `docs/install.md`).

Where the file lives: `HANDHELD_APP_PATH` (default `MEDIA_ROOT/handheld/birdROMs.muxapp`, so it sits
on the same volume as uploads). Until something is published the page says so.
