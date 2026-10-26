# 006 — Authenticated ROM downloads

## Decisions
- **Stream, don't redirect.** `download` opens the file with `rom.file.open("rb")` and returns a
  `FileResponse(as_attachment=True)`. This works with both FileSystemStorage and S3Storage, and the
  client never gets a storage URL (not even a short-lived signed one). The cost is that S3 bytes
  pass through the app. If that becomes a bottleneck, a later spec can switch to a signed redirect.
- **Media route removed completely**, not just guarded for non-DEBUG. Before, ROMs were public in
  dev too. Nothing else depended on it, because cover art is still an external URL.
- **Attachment filename = title + extension** (path separators replaced with `_`). The storage
  key can carry a dedup suffix (`zelda_OvlBGqX.nes`), and that showed up in the tests because the
  test media directory is shared across test cases.
- The serializer's `file` field is now `write_only` (upload only). A new `download_url` field points
  at the API endpoint, as an absolute URL when there is a request in context.
- Frontend: `api.downloadRom(rom)` uses a shared `rawRequest` (token header and error handling),
  reads `Content-Disposition` (including RFC 5987 `filename*`), and saves the file with an object URL.

## Notes for later specs
- 010 (thumbnails): if cover images are saved to storage, they need their own serving path. Do not
  bring back a blanket `static(MEDIA_URL)` route, because it would expose ROMs again.
- Still no git remote, so push is skipped.
