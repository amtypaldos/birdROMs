"""Env-driven settings for the in-place ROM library (a folder or an S3 bucket/prefix).

`LIBRARY_BACKEND=filesystem` reads `LIBRARY_ROOT`; `s3` reuses the `S3_*` storage settings with
an optional `LIBRARY_S3_PREFIX`. Unset, it follows `STORAGE_BACKEND` (an S3 install keeps an S3
library), else filesystem. See apps/roms/library.py.
"""

from dataclasses import dataclass

from .storage import _env_bool

LIBRARY_BACKENDS = ("filesystem", "s3")


@dataclass(frozen=True)
class LibrarySettings:
    backend: str = "filesystem"
    root: str = "/library"
    s3_prefix: str = ""
    read_only: bool = False
    write_covers: bool = True
    scan_crontab: str = "*/15 * * * *"
    guard_ratio: float = 0.25
    guard_min: int = 50


def parse_library_settings(env) -> LibrarySettings:
    """Build `LibrarySettings` from `LIBRARY_*` env vars; unknown backends raise `ValueError`."""
    backend = (env.get("LIBRARY_BACKEND") or env.get("STORAGE_BACKEND") or "filesystem").strip().lower()
    if backend not in LIBRARY_BACKENDS:
        raise ValueError(
            f"Unknown LIBRARY_BACKEND {backend!r}; expected one of: {', '.join(LIBRARY_BACKENDS)}"
        )
    defaults = LibrarySettings()
    return LibrarySettings(
        backend=backend,
        root=(env.get("LIBRARY_ROOT") or defaults.root).strip(),
        s3_prefix=(env.get("LIBRARY_S3_PREFIX") or "").strip(),
        read_only=_env_bool(env.get("LIBRARY_READ_ONLY"), defaults.read_only),
        write_covers=_env_bool(env.get("LIBRARY_WRITE_COVERS"), defaults.write_covers),
        scan_crontab=(env.get("LIBRARY_SCAN_CRONTAB") or defaults.scan_crontab).strip(),
        guard_ratio=float(env.get("LIBRARY_MISSING_GUARD_RATIO") or defaults.guard_ratio),
        guard_min=int(env.get("LIBRARY_MISSING_GUARD_MIN") or defaults.guard_min),
    )
