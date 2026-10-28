"""Platform folder-alias table: muOS folder names and aliases to canonical platforms."""

import csv
import functools
from dataclasses import dataclass
from pathlib import Path

UNSORTED_FOLDER = "_UNSORTED"
CSV_PATH = Path(__file__).parent / "data" / "platform_aliases.csv"

# Folders shared by two platforms, told apart by file extension.
_EXTENSION_SPLITS = {
    "NGP": {".ngc": "Neo Geo Pocket Color", ".ngp": "Neo Geo Pocket"},
    "WS": {".wsc": "WonderSwan Color", ".ws": "WonderSwan"},
}
_NON_GAME = "non-game"


@dataclass(frozen=True)
class PlatformInfo:
    name: str
    muos_folder: str
    kind: str  # game | arcade | non-game


@functools.cache
def _load():
    """Return (lookup by lower-cased folder or alias, info by canonical name)."""
    rows = []
    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            info = PlatformInfo(row["canonical_platform"], row["muos_folder"], row["kind"])
            rows.append((info, row["aliases"]))
    lookup: dict[str, PlatformInfo] = {}
    # Aliases win over folder names: a shared folder (SFC) resolves to its primary alias owner.
    for info, aliases in rows:
        for alias in aliases.split(";"):
            if alias.strip():
                lookup.setdefault(alias.strip().lower(), info)
    for info, _ in rows:
        if info.muos_folder:
            lookup.setdefault(info.muos_folder.lower(), info)
    by_name = {info.name: info for info, _ in rows}
    return lookup, by_name


def platform_for_folder(folder: str) -> PlatformInfo | None:
    """Resolve a library folder name (muOS folder or alias, any case) to a platform."""
    return _load()[0].get(folder.strip().lower())


def platform_for_game(folder: str, filename: str) -> PlatformInfo | None:
    """Resolve a game file's platform; None for unknown or non-game folders."""
    info = platform_for_folder(folder)
    if info is None or info.kind == _NON_GAME:
        return None
    split = _EXTENSION_SPLITS.get(info.muos_folder)
    if split:
        by_name = _load()[1]
        ext = Path(filename).suffix.lower()
        if ext in split:
            return by_name[split[ext]]
    return info


def muos_folder_for(platform: str) -> str | None:
    """The muOS folder for a canonical platform name, if it has one."""
    info = _load()[1].get(platform)
    return (info.muos_folder or None) if info else None
