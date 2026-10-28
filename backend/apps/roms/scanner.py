"""Diff the library listing against ROM rows: add new games, update changed ones, flag vanished
files missing (never delete), restore returning ones. Locking and scan history live in the caller.
"""

import posixpath
from dataclasses import dataclass, field

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from .library import IMGS_FOLDER, Library, LibraryUnavailable, get_library
from .models import ROM, LibraryScan
from .platform_aliases import platform_for_folder, platform_for_game
from .services import SUPPORTED_EXTENSIONS, get_extension, parse_rom_filename

GAME_EXTENSIONS = SUPPORTED_EXTENSIONS | frozenset(
    {
        ".zip", ".md", ".nes", ".gb", ".smc", ".gbc", ".sms", ".pce", ".gg", ".rom", ".gba", ".a26",
        ".mgw", ".ws", ".ngc", ".p8", ".chd", ".sfc", ".wsc", ".min", ".vb", ".pbp", ".nds", ".iso",
        ".pak", ".z64", ".v64", ".bin", ".cso", ".ngp", ".n64", ".7z", ".32x", ".a52", ".a78", ".lnx",
        ".fds", ".sgx", ".col", ".adf", ".d64", ".t64", ".prg", ".dsk", ".st", ".msa", ".mx1", ".mx2",
    }
)  # fmt: skip
MULTIFILE_EXTENSIONS = frozenset({".cue", ".gdi", ".m3u", ".ccd", ".mds"})
# Parts of a multi-file game, when their folder holds a descriptor (.cue, ...).
MULTIFILE_PART_EXTENSIONS = frozenset({".bin", ".img", ".raw", ".sub"})
COVER_EXTENSION = ".png"
BATCH_SIZE = 500
SCAN_LOCK_KEY = 0x62697264524F4D53  # "birdROMS": Postgres advisory lock key, one scan at a time


@dataclass
class ScanResult:
    added: int = 0
    changed: int = 0
    missing: int = 0
    restored: int = 0
    skipped_multifile: int = 0
    skipped_other: int = 0
    unknown_folders: list[str] = field(default_factory=list)
    aborted_reason: str = ""
    added_ids: list[int] = field(default_factory=list)


def _aborted(reason):
    return ScanResult(aborted_reason=reason)


def _classify(entries, depth):
    """Split the listing into games, covers and counters.

    Returns (games {path: (entry, folder)}, covers {(folder, stem): path}, result).
    """
    result = ScanResult()
    files = {}  # folder -> [entries directly in the system folder]
    covers = {}
    for entry in entries:
        parts = entry.path.split("/")[depth:]
        if len(parts) == 3:
            if get_extension(parts[2]) == COVER_EXTENSION:
                covers[(parts[0], posixpath.splitext(parts[2])[0])] = entry.path
        elif len(parts) == 2:
            files.setdefault(parts[0], []).append((entry, parts[1]))

    games = {}
    unknown = set()
    for folder, items in files.items():
        info = platform_for_folder(folder)
        if info is None:
            unknown.add(folder)
            continue
        if info.kind == "non-game":
            continue
        multifile = any(get_extension(name) in MULTIFILE_EXTENSIONS for _, name in items)
        for entry, name in items:
            ext = get_extension(name)
            if ext in MULTIFILE_EXTENSIONS or (multifile and ext in MULTIFILE_PART_EXTENSIONS):
                result.skipped_multifile += 1
            elif ext in GAME_EXTENSIONS:
                games[entry.path] = (entry, folder, name)
            else:
                result.skipped_other += 1
    result.unknown_folders = sorted(unknown)
    return games, covers, result


def _guard_reason(present, to_flag, guard_ratio, guard_min):
    if present >= guard_min and to_flag > guard_ratio * present:
        return (
            f"Refusing to flag {to_flag} of {present} games missing "
            f"(more than {guard_ratio:.0%}); accept removals to proceed."
        )
    return ""


def scan_library(library: Library, *, accept_removals: bool = False, guard_ratio: float, guard_min: int) -> ScanResult:
    """Sync ROM rows with the library listing; a guarded abort or unreachable library changes nothing."""
    try:
        entries = list(library.entries())
        depth = 1 if library.systems_prefix else 0
    except LibraryUnavailable as exc:
        return _aborted(str(exc))
    if not entries:
        return _aborted("The library has no systems folder or no files.")

    games, covers, result = _classify(entries, depth)
    for system, count in library.subfolders.items():
        info = platform_for_folder(system)
        if info is not None and info.kind != "non-game":
            result.skipped_other += count

    rows = ROM.objects.values("id", "file", "size_bytes", "modified_at", "missing", "cover_path")
    existing = {row["file"]: row for row in rows}
    present = sum(1 for row in existing.values() if not row["missing"])
    vanished = [row["id"] for path, row in existing.items() if path not in games and not row["missing"]]
    if not accept_removals and present and not games:
        return _aborted("The listing has no importable games; the library looks empty.")
    if not accept_removals:
        reason = _guard_reason(present, len(vanished), guard_ratio, guard_min)
        if reason:
            return _aborted(reason)

    to_create, to_update = [], []
    for path, (entry, folder, name) in games.items():
        cover = covers.get((folder, posixpath.splitext(name)[0]), "")
        row = existing.get(path)
        if row is None:
            parsed = parse_rom_filename(name)
            info = platform_for_game(folder, name)
            to_create.append(
                ROM(
                    title=parsed.title,
                    platform=info.name,
                    file=path,
                    filename=name,
                    extension=get_extension(name),
                    tags=list(parsed.tags),
                    source="library",
                    size_bytes=entry.size,
                    modified_at=entry.modified,
                    cover_path=cover,
                    uploaded_by=None,
                )
            )
            continue
        if row["missing"]:
            result.restored += 1
        elif (row["size_bytes"], row["modified_at"], row["cover_path"]) != (entry.size, entry.modified, cover):
            result.changed += 1
        else:
            continue
        to_update.append(
            ROM(id=row["id"], size_bytes=entry.size, modified_at=entry.modified, cover_path=cover, missing=False)
        )

    with transaction.atomic():
        for start in range(0, len(to_create), BATCH_SIZE):
            created = ROM.objects.bulk_create(to_create[start : start + BATCH_SIZE])
            result.added_ids.extend(rom.id for rom in created)
        fields = ["size_bytes", "modified_at", "cover_path", "missing"]
        ROM.objects.bulk_update(to_update, fields, batch_size=BATCH_SIZE)
        for start in range(0, len(vanished), BATCH_SIZE):
            ROM.objects.filter(id__in=vanished[start : start + BATCH_SIZE]).update(missing=True)
    result.added = len(to_create)
    result.missing = len(vanished)
    return result


def _try_scan_lock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [SCAN_LOCK_KEY])
        return cursor.fetchone()[0]


def _release_scan_lock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [SCAN_LOCK_KEY])


def run_library_scan(*, accept_removals: bool = False, library: Library | None = None) -> LibraryScan | None:
    """Run one locked scan and record it; None when another scan holds the lock.

    The row ends `ok`, `aborted` (reason in `message`) or `failed` (exception text in `message`),
    never `running`. After an `ok` scan, cover scrapes are queued for added ROMs without a cover.
    """
    if not _try_scan_lock():
        return None
    try:
        scan = LibraryScan.objects.create(accept_removals=accept_removals)
        try:
            config = settings.LIBRARY
            result = scan_library(
                library or get_library(),
                accept_removals=accept_removals,
                guard_ratio=config.guard_ratio,
                guard_min=config.guard_min,
            )
        except Exception as exc:
            scan.state, scan.message = "failed", f"{type(exc).__name__}: {exc}"
        else:
            for name in ("added", "changed", "missing", "restored", "skipped_multifile", "skipped_other"):
                setattr(scan, name, getattr(result, name))
            scan.unknown_folders = result.unknown_folders
            scan.state = "aborted" if result.aborted_reason else "ok"
            scan.message = result.aborted_reason
        scan.finished_at = timezone.now()
        scan.save()
        if scan.state == "ok":
            _enqueue_cover_scrapes(result.added_ids)
        return scan
    finally:
        _release_scan_lock()


def _enqueue_cover_scrapes(rom_ids):
    from birdroms import tasks  # deferred: tasks imports this module

    for rom_id in ROM.objects.filter(pk__in=rom_ids, cover_path="").values_list("pk", flat=True):
        tasks.scrape_rom_cover(rom_id)
