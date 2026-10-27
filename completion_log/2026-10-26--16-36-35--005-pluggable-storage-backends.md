# 005 — Pluggable storage backends — completed

**Implemented:** `django-storages[s3]` dependency (pyproject, uv.lock, requirements.txt);
`birdroms/storage.py::build_storages` selects filesystem (default) or S3-compatible storage
from `STORAGE_BACKEND`; `MEDIA_ROOT` is env-configurable; all storage vars documented in
`backend/.env.example`; README "File Storage" section added.

**Verified:** `uv run python manage.py test` → 26 tests OK (6 new: filesystem default,
S3 selection and instantiation with env options, optional-option omission, unknown-backend
rejection, test suite on filesystem, ROM upload save/read-back round trip). `manage.py check`
is clean. With `STORAGE_BACKEND=s3`, a manual check confirmed `default_storage` resolves to `S3Storage`.

**Follow-up:** no live S3/MinIO integration test. Push skipped because no git remote is configured.
