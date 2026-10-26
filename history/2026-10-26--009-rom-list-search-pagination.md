# 009 — ROM list pagination, search & platform filter

## Decisions
- **Hand-rolled filters in `get_queryset`** instead of adding `django-filter` or DRF's `SearchFilter`.
  There are only two params (`search` → `title__icontains`, `platform` → exact). DRF's `SearchFilter`
  splits on whitespace, and a new dependency was not worth it. The filters apply only to the `list`
  action, so detail routes such as download still resolve any ROM by id.
- **Pagination is set on the viewset** (`apps/roms/pagination.py`), not as a global
  `DEFAULT_PAGINATION_CLASS`. The other endpoints are not lists, so a global setting would add no
  behaviour. `page_size` is client-adjustable and capped at 100.
- **Stable ordering**: the queryset orders by `-uploaded_at, -id`. Rows with equal timestamps could
  otherwise repeat or go missing across pages.
- **`/api/roms/platforms/`** is a `detail=False` action, so it uses the same role permission as the
  list. It returns the distinct non-empty platforms sorted by name, as a plain JSON list.
- **Frontend**: one `query` state (`search`, `platform`, `page`) drives `loadRoms`. Changing a filter
  resets to page 1. Search runs on submit (Enter or the Search button), not on every keystroke. The
  platform dropdown applies as soon as it changes. A request-id ref stops slower, older responses
  from overwriting newer results. Refresh and upload reload the current query and the platform list.

## Notes for later specs
- 011/012: `RomList` now takes `romPage`, `query`, `platforms` and `onQuery`. `LibraryFilters` and
  `Pagination` are separate components, ready to restyle.
- The frontend `PAGE_SIZE` (24) must match the backend default. It is only used to show "Page X of Y".
