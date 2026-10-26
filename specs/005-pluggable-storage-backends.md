# 005 — Pluggable storage backends (local/NFS + S3-compatible)

## Status: COMPLETE
Priority: 5

## Problem / Context
ROMs and cover art are stored only on the local filesystem (`MEDIA_ROOT`). For self-hosting,
operators need to choose where large ROM files live — a local/NFS mount or S3-compatible object
storage (MinIO, Cloudflare R2, Backblaze B2, AWS S3). This must be selectable purely by env.

## Acceptance Criteria
- `django-storages` is added. A `STORAGE_BACKEND` env var selects the backend:
  - `filesystem` (default) — current behavior; NFS works simply by pointing `MEDIA_ROOT` at a
    mounted path. Zero extra config.
  - `s3` — S3-compatible storage configured entirely via env: endpoint URL, region, bucket,
    access key, secret key, optional custom/public domain, and path-style toggle (so MinIO/R2/B2
    all work, not just AWS).
- Both ROM files and cover-art images use the configured default storage.
- No credentials are committed; every S3 var is documented in `.env.example`.
- Switching backends requires no code changes — only env.

## Completion Signal
Implementation:
- [x] `django-storages` added; backend selected by `STORAGE_BACKEND`.
- [x] Filesystem (default) and S3-compatible configs implemented via env.
- [x] `.env.example` documents all storage vars.

Testing:
- [x] Backend test: with `filesystem`, an uploaded file round-trips (save + read back).
- [x] Backend test: backend-selection logic picks the S3 storage class when `STORAGE_BACKEND=s3`
      (no live S3 required — assert settings/storage wiring, mock as needed).
- [x] `uv run python manage.py test` passes.

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 1 -->
