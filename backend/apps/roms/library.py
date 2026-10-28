"""The ROM library: a muOS-layout tree (`ROMS/<SYSTEM>/<file>`, `ROMS/<SYSTEM>/Imgs/<png>`)
on a folder or in an S3 bucket, listed in place.

birdROMs never deletes, moves or overwrites anything here; `write_new` only creates files.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, Storage

SYSTEMS_FOLDERS = ("ROMS", "Roms")
IMGS_FOLDER = "imgs"


class LibraryUnavailable(Exception):
    """The library root or its systems folder can't be listed (share down, bucket unreachable)."""


@dataclass(frozen=True)
class LibraryEntry:
    path: str  # "/"-separated, relative to the library root
    size: int
    modified: datetime  # timezone-aware UTC


def _hidden(name):
    return name.startswith(".")


def _in_layout(relative_parts):
    """True for `<SYS>/<file>` and `<SYS>/<Imgs>/<file>` (parts relative to the systems folder)."""
    if any(not part or _hidden(part) for part in relative_parts):
        return False
    if len(relative_parts) == 2:
        return True
    return len(relative_parts) == 3 and relative_parts[1].lower() == IMGS_FOLDER


class Library(ABC):
    read_only = False
    # After `entries()` is exhausted: system folder name -> number of non-Imgs subfolders the
    # listing skipped (games inside subfolders are not imported).
    subfolders: dict[str, int]

    @property
    @abstractmethod
    def systems_prefix(self) -> str:
        """`"ROMS"`, `"Roms"`, or `""` when the system folders sit directly at the root."""

    @property
    @abstractmethod
    def writable(self) -> bool: ...

    @property
    @abstractmethod
    def storage(self) -> Storage:
        """A Django storage rooted at the library root."""

    @abstractmethod
    def entries(self) -> Iterator[LibraryEntry]: ...

    def exists(self, path: str) -> bool:
        return self.storage.exists(path)

    def write_new(self, path: str, data: bytes) -> None:
        """Create `path` with `data`; never overwrites."""
        if not self.writable:
            raise PermissionError("The library is read-only.")
        if self.exists(path):
            raise FileExistsError(path)
        self._write(path, data)

    @abstractmethod
    def _write(self, path: str, data: bytes) -> None: ...


class FilesystemLibrary(Library):
    def __init__(self, root: str, read_only: bool):
        self.root = root
        self.read_only = read_only

    @property
    def systems_prefix(self) -> str:
        try:
            names = {entry.name for entry in os.scandir(self.root) if entry.is_dir()}
        except OSError:
            return ""
        return next((name for name in SYSTEMS_FOLDERS if name in names), "")

    @property
    def writable(self) -> bool:
        return not self.read_only and os.access(self.root, os.W_OK)

    @property
    def storage(self) -> Storage:
        return FileSystemStorage(location=self.root)

    def _dirs(self, path):
        with os.scandir(path) as it:
            return [e for e in it if not _hidden(e.name) and e.is_dir()]

    def _files(self, path):
        with os.scandir(path) as it:
            for e in it:
                if not _hidden(e.name) and e.is_file():
                    yield e

    def _entry(self, dir_entry, prefix):
        stat = dir_entry.stat()
        return LibraryEntry(
            path=f"{prefix}{dir_entry.name}",
            size=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
        )

    def entries(self) -> Iterator[LibraryEntry]:
        systems = self.systems_prefix
        base = os.path.join(self.root, systems) if systems else self.root
        lead = f"{systems}/" if systems else ""
        self.subfolders = {}
        try:
            system_dirs = self._dirs(base)
            for system in system_dirs:
                prefix = f"{lead}{system.name}/"
                subdirs = []
                with os.scandir(system.path) as it:
                    for e in it:
                        if _hidden(e.name):
                            continue
                        if e.is_dir():
                            if e.name.lower() == IMGS_FOLDER:
                                subdirs.append(e)
                            else:
                                self.subfolders[system.name] = self.subfolders.get(system.name, 0) + 1
                        elif e.is_file():
                            yield self._entry(e, prefix)
                for imgs in subdirs:
                    for e in self._files(imgs.path):
                        yield self._entry(e, f"{prefix}{imgs.name}/")
        except OSError as exc:
            raise LibraryUnavailable(f"Cannot list the library at {self.root}: {exc}") from exc

    def _write(self, path, data):
        target = self.storage.path(path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "xb") as handle:  # "x": fail rather than overwrite on a race
            handle.write(data)


class S3Library(Library):
    def __init__(self, storage, prefix: str, read_only: bool):
        self._storage = storage
        self.prefix = prefix.strip("/")
        self.read_only = read_only

    @property
    def _list_prefix(self):
        return f"{self.prefix}/" if self.prefix else ""

    @property
    def systems_prefix(self) -> str:
        objects = self._storage.bucket.objects
        for name in SYSTEMS_FOLDERS:
            if next(iter(objects.filter(Prefix=f"{self._list_prefix}{name}/")), None) is not None:
                return name
        return ""

    @property
    def writable(self) -> bool:
        return not self.read_only

    @property
    def storage(self) -> Storage:
        return self._storage

    def entries(self) -> Iterator[LibraryEntry]:
        cut = len(self._list_prefix)
        try:
            found = [
                LibraryEntry(obj.key[cut:], obj.size, obj.last_modified.astimezone(timezone.utc))
                for obj in self._storage.bucket.objects.filter(Prefix=self._list_prefix)
            ]
        except Exception as exc:  # botocore errors: unreachable, bad credentials, no bucket
            raise LibraryUnavailable(f"Cannot list the S3 library: {exc}") from exc
        if not found:
            raise LibraryUnavailable("The S3 library is empty or unreachable.")
        systems = next((n for n in SYSTEMS_FOLDERS if any(e.path.startswith(f"{n}/") for e in found)), "")
        depth = len(systems.split("/")) if systems else 0
        self.subfolders = {}
        seen = set()
        for entry in found:
            parts = entry.path.split("/")
            if systems and parts[0] != systems:
                continue
            rel = parts[depth:]
            if (
                len(rel) >= 3
                and not any(not part or _hidden(part) for part in rel)
                and rel[1].lower() != IMGS_FOLDER
                and (rel[0], rel[1]) not in seen
            ):
                seen.add((rel[0], rel[1]))
                self.subfolders[rel[0]] = self.subfolders.get(rel[0], 0) + 1
            if _in_layout(parts[depth:]):
                yield entry

    def _write(self, path, data):
        self._storage.save(path, ContentFile(data))


def get_library() -> Library:
    """The library configured by `settings.LIBRARY`."""
    config = settings.LIBRARY
    if config.backend == "s3":
        from storages.backends.s3 import S3Storage

        from birdroms.storage import _s3_options

        options = {**_s3_options(os.environ), "location": config.s3_prefix.strip("/"), "file_overwrite": False}
        return S3Library(S3Storage(**options), config.s3_prefix, config.read_only)
    return FilesystemLibrary(config.root, config.read_only)


def library_storage() -> Storage:
    """Callable storage for `FileField(storage=...)`, rooted at the library."""
    return get_library().storage
