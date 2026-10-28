"""Diff the library listing against ROM rows: add new games, update changed ones, flag vanished
files missing (never delete), restore returning ones. Locking and scan history live in the caller.
"""

import logging
import posixpath
from dataclasses import dataclass, field

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from .library import IMGS_FOLDER, Library, LibraryUnavailable, get_library
from .models import ROM, LibraryScan
from .platform_aliases import UNSORTED_FOLDER, platform_for_folder, platform_for_game
from .services import (
    ROM_EXTENSIONS,
    classify_platform_from_extension,
    get_extension,
    parse_rom_filename,
)

MULTIFILE_EXTENSIONS = frozenset({".cue", ".gdi", ".m3u", ".ccd", ".mds"})
# Parts of a multi-file game, when their folder holds a descriptor (.cue, ...).
MULTIFILE_PART_EXTENSIONS = frozenset({".bin", ".img", ".raw", ".sub"})
COVER_EXTENSION = ".png"
BATCH_SIZE = 500
logger = logging.getLogger(__name__)
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

    Returns (games {path: (entry, folder, name, platform)}, covers {(folder, lower stem): path},
    result). Files directly in `_UNSORTED` (uploads with no muOS folder) are games whatever their
    extension's multi-file role, their platform taken from the extension.
    """
    result = ScanResult()
    files = {}  # folder -> [entries directly in the system folder]
    covers = {}
    for entry in entries:
        parts = entry.path.split("/")[depth:]
        if len(parts) == 3:
            if get_extension(parts[2]) == COVER_EXTENSION:
                key = (parts[0], posixpath.splitext(parts[2])[0].lower())
                # Several case variants of one cover: prefer an `Imgs` folder, then the first path.
                covers[key] = min(covers.get(key, entry.path), entry.path, key=_cover_rank)
        elif len(parts) == 2:
            files.setdefault(parts[0], []).append((entry, parts[1]))

    games = {}
    unknown = set()
    for folder, items in files.items():
        if folder.lower() == UNSORTED_FOLDER.lower():
            for entry, name in items:
                if get_extension(name) in ROM_EXTENSIONS:
                    games[entry.path] = (entry, folder, name, classify_platform_from_extension(name))
                else:
                    result.skipped_other += 1
            continue
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
            elif ext in ROM_EXTENSIONS:
                games[entry.path] = (entry, folder, name, platform_for_game(folder, name).name)
            else:
                result.skipped_other += 1
    result.unknown_folders = sorted(unknown)
    return games, covers, result


def _cover_rank(path):
    return (path.split("/")[-2] != "Imgs", path)


def _guard_reason(present, to_flag, guard_ratio, guard_min):
    if present >= guard_min and to_flag > guard_ratio * present:
        return (
            f"Refusing to flag {to_flag} of {present} games missing "
            f"(more than {guard_ratio:.0%}); accept removals to proceed."
        )
    return ""


def scan_library(library: Library, *, accept_removals: bool = False, guard_ratio: float, guard_min: int) -> ScanResult:
    """Sync ROM rows with the library listing; a guarded abort or unreachable library changes nothing.

    A row is flagged missing only when its path is absent from the whole listing and a re-check
    confirms the file is gone in that exact case (a case-only rename is a new game); rows loaded
    before listing so an upload landing mid-scan is never flagged, and one that gains a row
    mid-scan is not created twice.
    """
    rows = ROM.objects.order_by().values("id", "file", "size_bytes", "modified_at", "missing", "cover_path")
    existing = {row["file"]: row for row in rows}
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

    present = sum(1 for row in existing.values() if not row["missing"])
    if not accept_removals and present and not games:
        return _aborted("The listing has no importable games; the library looks empty.")
    listed = {entry.path for entry in entries}
    names = {}  # folder -> child names, shared by the re-checks
    try:
        vanished = [
            row["id"]
            for path, row in existing.items()
            if not row["missing"] and path not in listed and not library.exists_exact(path, names)
        ]
    except LibraryUnavailable as exc:
        return _aborted(str(exc))
    if not accept_removals:
        reason = _guard_reason(present, len(vanished), guard_ratio, guard_min)
        if reason:
            return _aborted(reason)

    to_create, to_update = {}, []
    for path, (entry, folder, name, platform) in games.items():
        cover = covers.get((folder, posixpath.splitext(name)[0].lower()), "")
        row = existing.get(path)
        if row is None:
            parsed = parse_rom_filename(name)
            to_create[path] = ROM(
                title=parsed.title,
                platform=platform,
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
        paths = list(to_create)
        for start in range(0, len(paths), BATCH_SIZE):
            # Uploaded since the rows were loaded: the upload's row stands.
            for path in ROM.objects.filter(file__in=paths[start : start + BATCH_SIZE]).values_list("file", flat=True):
                del to_create[path]
        new = list(to_create.values())
        for start in range(0, len(new), BATCH_SIZE):
            created = ROM.objects.bulk_create(new[start : start + BATCH_SIZE])
            result.added_ids.extend(rom.id for rom in created)
        fields = ["size_bytes", "modified_at", "cover_path", "missing"]
        ROM.objects.bulk_update(to_update, fields, batch_size=BATCH_SIZE)
        for start in range(0, len(vanished), BATCH_SIZE):
            ROM.objects.filter(id__in=vanished[start : start + BATCH_SIZE]).update(missing=True)
    result.added = len(new)
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
    never `running`. After an `ok` scan, once the lock is released, cover scrapes are queued for
    added ROMs without a cover.
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
    finally:
        _release_scan_lock()
    if scan.state == "ok":
        _enqueue_cover_scrapes(result.added_ids)
    return scan


def _enqueue_cover_scrapes(rom_ids):
    from birdroms import tasks  # deferred: tasks imports this module

    try:
        for rom_id in ROM.objects.filter(pk__in=rom_ids, cover_path="").values_list("pk", flat=True):
            tasks.scrape_rom_cover(rom_id)
    except Exception:
        logger.exception("Could not queue cover scrapes after a library scan")
