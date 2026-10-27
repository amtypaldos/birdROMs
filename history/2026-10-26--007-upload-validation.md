# 007 — ROM upload validation

## Decisions
- **The allowlist is `SUPPORTED_EXTENSIONS`** from the spec-004 platform map. `.zip`/`.7z` are
  already in it as "Archive", so there is no second list to keep in sync. The check uses
  `get_extension`, the same helper the model uses for classification, so validation and
  auto-classification always agree on what the extension is.
- **Empty files** are rejected by DRF's `FileField` default (`allow_empty_file=False`), so no
  custom code was needed. A test pins this behavior.
- **`MAX_ROM_UPLOAD_BYTES`** is parsed in `birdroms/uploads.py` and fails fast with
  `ImproperlyConfigured` on non-integer or non-positive values. The default is 2 GiB (2147483648).
- The size check runs after Django has already received the upload, in the serializer, where the
  spec requires it. Truly huge bodies should also be capped at the reverse proxy; the docs say so.

## Notes for later specs
- 013 (deployment): set nginx `client_max_body_size` to at least `MAX_ROM_UPLOAD_BYTES`.
- 011 (UI): the 400 messages on `file` are written to be shown to users as-is.
