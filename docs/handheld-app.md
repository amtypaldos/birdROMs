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


## Nintendo Switch distribution

The same Handheld page also offers the native RetroArch ROM downloader for Nintendo Switch.
The Switch build is a separate artifact; the default muOS API response and `.muxapp` are unchanged.
Normal website session authentication and paired `Device` tokens work on both endpoints:

- `GET /api/handheld/?platform=switch` returns availability and verified release metadata.
- `GET /api/handheld/download/?platform=switch` downloads `birdROMs-switch.zip` personalized
  with this server's URL. Unknown `platform` values return HTTP 400; omitted values select muOS.

The metadata includes `platform`, date `version` (`YYYY.MM.DD[.N]`), `filename`, stored ZIP `size`
and `sha256`, executable `nro_size` and `nro_sha256`, and `published_at`. The ZIP hash describes
what was published **before** personalization; the NRO hash remains valid in personalized downloads.
These fields support an authenticated device checking the self-hosted server for updates.

### Publish or bundle a Switch release

```sh
python manage.py publish_handheld --platform switch path/to/birdROMs-switch.zip
```

`SWITCH_APP_PATH` defaults to `MEDIA_ROOT/handheld/birdROMs-switch.zip`; it is independent of
`HANDHELD_APP_PATH`. Publishing validates a temporary copy before replacing the old release.
Invalid packages leave the previous release intact. The image workflow fetches the Switch artifact
from the handheld release tag pinned in [`switch-version`](../switch-version), alongside the
muOS artifact pinned in `handheld-version`. Both artifacts must exist before building the backend
image. The existing `HANDHELD_RELEASE_TOKEN` also grants access to the Switch release asset.
A deployment that ships no Switch bundle can still start; the absent bundle is a no-op.

On startup, `install_bundled_handheld --platform switch` publishes the bundled archive only when
its bytes differ. To change the bundled source location, set `BUNDLED_SWITCH_PATH` (default
`/app/birdROMs-switch.zip`). Rebuild the backend image after changing the release pin; a site-only
frontend rebuild does not change the package already stored in the media volume.

The accepted release archive contains only:

```text
switch/
  birdroms/
    birdroms.nro
    version.json
    server.json        # optional public origin seed, replaced for every download
```

The manifest has exactly `platform: "switch"`, `version`, `nro_sha256`, and `nro_size`.
The publisher verifies the NRO magic, SHA-256 and byte length. Duplicate entries, traversal,
absolute paths, symlinks, special files, encrypted entries, excess files, and oversized entries
are rejected. `config.json` and authentication tokens never belong in a release archive.
An optional published seed may contain only `server_url`, a public HTTP(S) origin without
credentials, a path, or query parameters. Private installation addresses must not be published
as release defaults. Downloads replace that seed with the current request's server origin;
no user credentials or device token are inserted.

### Install and update on Switch

Extract the personalized ZIP to the SD root, producing
`sdmc:/switch/birdroms/birdroms.nro` and the server seed. Launch from Homebrew Menu, then approve
the displayed pairing request in the website. This is homebrew for managing RetroArch ROM files;
it does not install Switch titles, modify firmware, or include emulator cores.

The writable `sdmc:/switch/birdroms/config.json` belongs to the device and is never included in
server packages. Existing installations retain that configuration and pairing state during an
update; the updater ignores the new seed when a writable configuration already exists.
Use full-memory Homebrew Menu mode for larger libraries; physical hardware validation remains
part of the handheld project's release checklist.
