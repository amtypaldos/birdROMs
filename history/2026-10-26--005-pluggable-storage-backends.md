# 005 — Pluggable storage backends

## Decisions
- Storage selection lives in `backend/birdroms/storage.py` as `build_storages(env)`. It is a pure
  function that returns the Django `STORAGES` dict, so tests can check how a backend is picked
  without patching `os.environ` or reloading settings.
- `MEDIA_ROOT` can now be set from env, which is how NFS is supported.
- S3 defaults are chosen for privacy: `default_acl=None`, `querystring_auth=True` (signed URLs,
  can be overridden with `S3_QUERYSTRING_AUTH`), and `file_overwrite=False`. Optional
  options (endpoint, region, custom domain, location) are only passed through when set.
  `S3_PATH_STYLE=true` maps to `addressing_style="path"` for MinIO.
- An unknown `STORAGE_BACKEND` raises `ValueError` at settings import (fail fast).
- Test mode always forces filesystem storage, so a developer's `.env` with s3 can't leak into tests.

## Notes for later specs
- Cover art is currently only a URL field. When 010 downloads images, save them with
  `default_storage` (or an ImageField/FileField) so they follow the configured backend.
- 006 (authenticated downloads): under S3, `rom.file.path` does not exist. Stream through
  `rom.file.open()` or redirect to a signed `rom.file.url`; never use filesystem paths.
- Still no git remote, so push is skipped.
