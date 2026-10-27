# 004 — Expanded platform & file-type support

## Decisions
- Classification now looks up the final suffix (`os.path.splitext` on the basename) instead of
  scanning the map with `endswith`. The old approach misread `.smd` as `.md` and depended on
  dict order; a dict lookup is exact and O(1).
- `ROM.save()` reuses `get_extension()` from services, so the stored `extension` and the
  classification always agree. A dotfile such as `.nes` has no extension and is `unknown`.
- `.chd` is a generic "Disc Image" (Saturn, PS1, PS2, Dreamcast and Sega CD all use it).
  `.gdi`/`.cdi` are Dreamcast-specific in practice, so they map to "Sega Dreamcast".
  `.pbp` → PlayStation, `.cso` → PSP.
- `.ngc` maps to Neo Geo Pocket Color, per the spec (it is not GameCube).
- Game Gear is now labeled "Sega Game Gear" (it was "Game Gear"). No migration is needed and
  there is no production data yet.
- Derived constants: `SUPPORTED_EXTENSIONS` (a frozenset, for spec 007's allowlist) and
  `SUPPORTED_PLATFORMS` (a sorted tuple, for spec 009's filter). Labels live in
  `DISC_IMAGE`, `ARCHIVE` and `UNKNOWN_PLATFORM`.

## Notes for later specs
- 007: build the allowlist from `SUPPORTED_EXTENSIONS` and compare it against `get_extension()`.
- There is still no git remote, so push is skipped.
